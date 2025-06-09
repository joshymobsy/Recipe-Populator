import csv
import os
from urllib.parse import urlparse, parse_qs, urlencode

def format_image_url_for_csv(url):
    """
    Formats image URLs for images.weserv.nl by ensuring specific
    width, height, fit, and quality parameters are set.
    Handles existing parameters by overriding them.
    """
    if not url:
        return ''

    # Check if the URL is already using images.weserv.nl
    if url.startswith('https://images.weserv.nl'):
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)

        # Add or override w, h, fit, q with WebP optimization
        query_params['w'] = ['640']
        query_params['h'] = ['640']
        query_params['fit'] = ['cover']
        query_params['q'] = ['75']
        query_params['output'] = ['webp']  # Use WebP format for better compression
        query_params['af'] = ['']    # Enable auto-format
        query_params['il'] = ['']    # Enable interlacing

        # Reconstruct the query string
        new_query = urlencode(query_params, doseq=True)
        
        # Reconstruct the URL
        return parsed_url._replace(query=new_query).geturl()
    else:
        # If it's not an images.weserv.nl URL, don't modify it.
        # This function is specifically for modifying existing images.weserv.nl URLs in the CSV.
        return url

def update_csv_image_urls(input_csv_path, output_csv_path):
    updated_rows = []
    with open(input_csv_path, 'r', newline='', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames
        
        if 'Image' not in fieldnames or 'Chef Image' not in fieldnames:
            print("Error: 'Image' or 'Chef Image' columns not found in CSV.")
            return False

        for row in reader:
            # Update 'Image' column
            if 'Image' in row and row['Image']:
                row['Image'] = format_image_url_for_csv(row['Image'])
            
            # Update 'Chef Image' column
            if 'Chef Image' in row and row['Chef Image']:
                row['Chef Image'] = format_image_url_for_csv(row['Chef Image'])
            updated_rows.append(row)

    with open(output_csv_path, 'w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(updated_rows)
    return True

# Define paths
csv_file = 'mob_recipes_local.csv'
temp_csv_file = 'mob_recipes_local_temp.csv'

print(f"Updating image URLs in {csv_file}...")
if update_csv_image_urls(csv_file, temp_csv_file):
    os.replace(temp_csv_file, csv_file)
    print(f"Successfully updated image URLs in {csv_file}")
else:
    print(f"Failed to update {csv_file}") 