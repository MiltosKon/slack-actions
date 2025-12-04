import os
import re
import time
import requests
import yt_dlp
from slack_bolt import App
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# --- YouTube Utils (yt-dlp) ---

def get_video_data(url):
    """
    Fetches video metadata (title, description) and transcript using yt-dlp.
    Returns: (title, description, transcript_text)
    """
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['en'],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            title = info.get('title', 'Unknown Title')
            description = info.get('description', 'No description found.')
            
            # Transcript Extraction
            transcript_text = ""
            captions = info.get('automatic_captions') or info.get('subtitles')
            
            if captions:
                # Try to find English captions
                # 'en' is standard, but sometimes it's 'en-orig' or 'en-US'
                # We'll look for any key starting with 'en'
                en_key = next((k for k in captions.keys() if k.startswith('en')), None)
                
                if en_key:
                    tracks = captions[en_key]
                    # Prefer 'json3' format for easy parsing, fallback to 'vtt'
                    # We need the URL to fetch it
                    track_url = next((t['url'] for t in tracks if t['ext'] == 'json3'), None)
                    
                    if track_url:
                        try:
                            r = requests.get(track_url)
                            r.raise_for_status()
                            data = r.json()
                            
                            # Parse JSON3 format
                            # Structure: {'events': [{'segs': [{'utf8': 'text'}]}]}
                            text_parts = []
                            for event in data.get('events', []):
                                if 'segs' in event:
                                    for seg in event['segs']:
                                        if 'utf8' in seg:
                                            text_parts.append(seg['utf8'])
                            transcript_text = "".join(text_parts) # json3 segments often include spaces
                        except Exception as e:
                            print(f"Error fetching/parsing transcript JSON: {e}")
                    else:
                        print("No JSON3 caption track found.")
                else:
                    print("No English captions found.")
            else:
                print("No captions found.")

            return title, description, transcript_text

    except Exception as e:
        print(f"Error in yt-dlp: {e}")
        return None, None, None

# --- AI Agent ---

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def analyze_transcript(transcript_text, video_title, video_description, github_url):
    """
    Analyzes the transcript using Gemini to provide a summary, QA, and project ideas.
    """
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY not found."

    model = genai.GenerativeModel('gemini-2.5-flash')

    prompt = f"""
You are a senior QA Engineer and GitHub trends analyst, expert in API testing, automation, and SRE.

Analyze the following GitHub-trends YouTube video and return a SHORT, SLACK-FRIENDLY message.

User context: Mid-senior QA at a sportsbook platform, building ReportPortal visualizers, Slack workflows, and IoT smart locks.

VIDEO META
Title: {video_title}
Repo URL: {github_url}
Description: {video_description}

TRANSCRIPT (TRUNCATED)
{transcript_text[:25000]}

FORMAT YOUR ANSWER EXACTLY LIKE THIS (INCLUDING BLANK LINES):

*Summary*
[1-2 sentences max. No line breaks here.]

*Key Takeaways & QA*
- [Bullet 1 - max 1 line]
- [Bullet 2 - max 1 line]
- [Bullet 3 - max 1 line]

*Project Ideas*
1. **Work repo automation:** [one sentence, focus on CI/CD, API testing, k6, ReportPortal]
2. **Personal IoT:** [one sentence, focus side projects]

*GitHub repo link*
{github_url or "N/A"}

RULES
- Max 180 words total.
- Add a blank line between sections.
- Do NOT merge sections together; each heading must be followed by its own content and then a blank line.
- Use only top-3, most actionable ideas for this specific user.
"""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error generating AI analysis: {e}"

# --- Main Batch Job ---

def batch_job():
    slack_token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = os.getenv("SLACK_CHANNEL_ID")

    if not slack_token or not channel_id:
        print("Error: SLACK_BOT_TOKEN or SLACK_CHANNEL_ID not found.")
        return

    app = App(token=slack_token)

    # 1. Get Bot User ID
    try:
        auth_test = app.client.auth_test()
        bot_user_id = auth_test["user_id"]
        print(f"Bot User ID: {bot_user_id}")
    except Exception as e:
        print(f"Error authenticating: {e}")
        return

    # 2. Fetch History (last 20 messages)
    print(f"Fetching history for channel {channel_id}...")
    try:
        history = app.client.conversations_history(channel=channel_id, limit=20)
    except Exception as e:
        print(f"Error fetching history: {e}")
        return

    messages = history.get("messages", [])
    print(f"Found {len(messages)} messages.")

    for msg in messages:
        text = msg.get("text", "")
        ts = msg.get("ts")
        
        # Check for YouTube link
        url_match = re.search(r"(https?://(www\.)?(youtube\.com|youtu\.be)/[^\s]+)", text)
        if not url_match:
            continue

        print(f"Found YouTube link in message {ts}: {url_match.group(0)}")

        # 3. Check if already replied
        # We need to check the thread replies
        if "thread_ts" in msg:
            thread_ts = msg["thread_ts"]
        else:
            thread_ts = ts # If no thread yet, the message ts is the thread starter

        # Fetch thread replies
        try:
            replies = app.client.conversations_replies(channel=channel_id, ts=thread_ts)
            reply_messages = replies.get("messages", [])
            
            already_replied = False
            for reply in reply_messages:
                if reply.get("user") == bot_user_id:
                    already_replied = True
                    break
            
            if already_replied:
                print(f"  -> Found a video already processed ({ts}). Stopping search.")
                break

        except Exception as e:
            print(f"  -> Error checking replies: {e}")
            continue

        # 4. Process Video
        print(f"  -> Processing new video...")
        url = url_match.group(0)
        
        # Use yt-dlp to get everything
        title, description, transcript = get_video_data(url)
        
        if not title or not transcript:
            print("  -> Could not fetch video data or transcript.")
            continue

        # Extract GitHub URLs from description
        github_urls = re.findall(r"(https?://github\.com/[^\s]+)", description)
        github_url = github_urls[0] if github_urls else "N/A"

        analysis = analyze_transcript(transcript, title, description, github_url)

        # 5. Post Reply
        print("  -> Posting reply...")
        try:
            app.client.chat_postMessage(
                channel=channel_id,
                thread_ts=ts,
                text=analysis
            )
            print("  -> Done.")
        except Exception as e:
            print(f"  -> Error posting reply: {e}")
        
        # Sleep briefly to avoid rate limits
        time.sleep(2)

if __name__ == "__main__":
    batch_job()
