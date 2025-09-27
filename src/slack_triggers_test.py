import requests
import xlsxwriter
import os

def fetch_pokemon_data(pokemon_name):
    url = f"https://pokeapi.co/api/v2/pokemon/{pokemon_name.lower()}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Warning: Failed to fetch data for {pokemon_name}")
        return None

def parse_pokemon_stats(raw_data):
    stats_obj = {}
    for stat_entry in raw_data.get('stats', []):
        stat_name = stat_entry.get('stat', {}).get('name', '')
        base_stat = stat_entry.get('base_stat', '')
        stats_obj[stat_name] = base_stat

    return {
        "name": raw_data.get("name", ""),
        "stats": {
            "hp": stats_obj.get("hp", ""),
            "attack": stats_obj.get("attack", ""),
            "defense": stats_obj.get("defense", ""),
            "special-attack": stats_obj.get("special-attack", ""),
            "special-defense": stats_obj.get("special-defense", ""),
            "speed": stats_obj.get("speed", "")
        }
    }

def create_pokemon_stats_object(pokemon_names):
    pokemon_summary = []
    for name in pokemon_names:
        raw_data = fetch_pokemon_data(name)
        if raw_data:
            parsed = parse_pokemon_stats(raw_data)
            pokemon_summary.append(parsed)
    return {"pokemons": pokemon_summary}


def create_excel(pokemon_obj, filename="pokemon_stats.xlsx"):
    # Ensure output directory exists
    output_dir = "outputs"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    filepath = os.path.join(output_dir, filename)
    workbook = xlsxwriter.Workbook(filepath)
    worksheet = workbook.add_worksheet()

    headers = ["Name", "HP", "Attack", "Defense", "Special Attack", "Special Defense", "Speed"]
    worksheet.write_row(0, 0, headers)

    for row_num, pokemon in enumerate(pokemon_obj["pokemons"], start=1):
        stats = pokemon["stats"]
        row = [
            pokemon["name"].capitalize(),
            stats.get("hp", ""),
            stats.get("attack", ""),
            stats.get("defense", ""),
            stats.get("special-attack", ""),
            stats.get("special-defense", ""),
            stats.get("speed", "")
        ]
        worksheet.write_row(row_num, 0, row)

    workbook.close()
    print(f"Excel file '{filepath}' created with Pokémon stats.")

def main():
    pokemons = ["pikachu", "bulbasaur", "charizard", "squirtle", "mewtwo"]
    pokemon_obj = create_pokemon_stats_object(pokemons)
    create_excel(pokemon_obj)

if __name__ == "__main__":
    main()
