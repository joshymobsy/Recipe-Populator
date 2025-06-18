import csv
import os
from datetime import datetime

def update_pescatarian_dietary():
    # Create backup of the original file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"mob_recipes_local_backup_{timestamp}.csv"
    os.system(f"cp mob_recipes_local.csv {backup_file}")
    
    # Read the CSV file
    rows = []
    with open('mob_recipes_local.csv', 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        
        # Process each row
        for row in reader:
            # Check if Description contains 'pescatarian' (case-insensitive)
            if 'pescatarian' in row.get('Description', '').lower():
                row['Dietary Requirements'] = 'Pescatarian'
            rows.append(row)
    
    # Write the updated data back to the CSV
    with open('mob_recipes_local.csv', 'w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"Backup created as: {backup_file}")
    print("CSV file has been updated with Pescatarian dietary requirements.")

if __name__ == "__main__":
    update_pescatarian_dietary() 