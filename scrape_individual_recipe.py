import requests
from bs4 import BeautifulSoup
import csv
import re
import time
import json
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import logging
from datetime import datetime
import os
from playwright.sync_api import sync_playwright

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)

class IndividualRecipeScraper:
    def __init__(self):
        self.base_url = "https://www.mob.co.uk"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        self.rate_limit_delay = 2
        self.max_retries = 3
        self.backup_file = f'mob_recipes_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

    def make_request(self, url, retry_count=0):
        """Make a request using Playwright with retries"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_extra_http_headers(self.headers)
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                # Wait for the main recipe content to load
                page.wait_for_selector('h1', timeout=60000)
                content = page.content()
                browser.close()
                return content
        except Exception as e:
            if retry_count < self.max_retries:
                logging.warning(f"Request failed with Playwright, retrying ({retry_count + 1}/{self.max_retries}): {str(e)}")
                time.sleep(self.rate_limit_delay * (retry_count + 1))
                return self.make_request(url, retry_count + 1)
            else:
                logging.error(f"Max retries reached for URL {url} with Playwright: {str(e)}")
                raise

    def _extract_json_ld(self, soup):
        """Extract and parse JSON-LD data from the page"""
        json_ld_data = []
        for script_tag in soup.find_all('script', type='application/ld+json'):
            try:
                json_data = json.loads(script_tag.string)
                if isinstance(json_data, list):
                    json_ld_data.extend(json_data)
                else:
                    json_ld_data.append(json_data)
            except json.JSONDecodeError as e:
                logging.error(f"Error decoding JSON-LD: {e}")
        return json_ld_data

    def clean_time_format(self, time_text):
        """Clean up the time format"""
        if not time_text:
            return ''
        # Remove 'minscook' and 'hrcook'
        time_text = time_text.replace('minscook', 'mins').replace('hrcook', 'hr')
        # Ensure consistent spacing
        time_text = re.sub(r'\s+', ' ', time_text).strip()
        return time_text

    def strip_cropping_from_url(self, url):
        """Remove cropping/resizing segments from mob-cdn image URLs"""
        if not url:
            return url
        return re.sub(r'/(_[0-9]+x[0-9]+_crop_[^/]+/)', '/', url)

    def format_image_url(self, url):
        """Format image URL for use with images.weserv.nl"""
        if not url:
            return ''
        # Base parameters for resizing and quality
        params = "w=640&h=640&fit=cover&q=75"

        if not url.startswith('https://images.weserv.nl'):
            if 'mob-cdn.co.uk' in url:
                return f"https://images.weserv.nl/?url={url}&{params}"
            elif url.startswith('//'):
                return f"https://images.weserv.nl/?url=https:{url}&{params}"
            elif url.startswith('/'):
                return f"https://images.weserv.nl/?url={self.base_url}{url}&{params}"
        
        # If it's already an images.weserv.nl URL, ensure it has the desired parameters
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)

        # Add or override w, h, fit, q
        query_params['w'] = ['640']
        query_params['h'] = ['640']
        query_params['fit'] = ['cover']
        query_params['q'] = ['75']

        # Reconstruct the query string
        new_query = urlencode(query_params, doseq=True)
        
        # Reconstruct the URL
        return parsed_url._replace(query=new_query).geturl()

    def scrape_recipe(self, recipe_url):
        """Scrape an individual recipe page, prioritizing the RecipeHero section"""
        try:
            logging.info(f"Scraping recipe: {recipe_url}")
            html_content = self.make_request(recipe_url)
            soup = BeautifulSoup(html_content, 'html.parser')
            recipe_data = {
                'Image': '',
                'Title': '',
                'Time': '',
                'Chef Name': '',
                'Chef Image': '',
                'Description': '',
                'Dietary Requirements': 'None'
            }

            # --- PRIORITY: Extract from RecipeHero section ---
            hero = soup.find('div', class_=re.compile(r'RecipeHero( |$)'))
            if hero:
                # Title
                title_elem = hero.find('h1', class_=re.compile(r'RecipeHero__heading'))
                if title_elem:
                    recipe_data['Title'] = title_elem.get_text(strip=True)

                # Description
                desc_outer = hero.find('div', class_=re.compile(r'body-text-sm'))
                if desc_outer:
                    desc_inner = desc_outer.find('div', class_=re.compile(r'line-clamp-2|md:line-clamp-5'))
                    if desc_inner:
                        recipe_data['Description'] = desc_inner.get_text(strip=True)

                # Time (handle both 'mins' and 'hr' and combinations)
                meta = hero.find('div', class_=re.compile(r'RecipeHero_meta'))
                if meta:
                    # Find the div that contains the time string
                    for div in meta.find_all('div'):
                        text = div.get_text(strip=True)
                        # Regex to match '1 hr', '25 mins', '1 hr 30 mins', etc.
                        match = re.search(r'(\d+\s*hr(?:\s*\d+\s*mins?)?|\d+\s*mins?)', text)
                        if match:
                            recipe_data['Time'] = match.group(0)
                            break

                # Chef Name & Image
                chef_link = hero.find('a', href=re.compile(r'^/chefs/'))
                if chef_link:
                    chef_name_elem = chef_link.find('h3')
                    if chef_name_elem:
                        recipe_data['Chef Name'] = chef_name_elem.get_text(strip=True)
                    img_tag = chef_link.find('img')
                    if img_tag and img_tag.get('src'):
                        recipe_data['Chef Image'] = img_tag['src']

                # Main Recipe Image
                media_container = hero.find('div', class_=re.compile(r'RecipeHero__mediaContainer'))
                if media_container:
                    img_tag = media_container.find('img')
                    if img_tag and img_tag.get('src'):
                        recipe_data['Image'] = img_tag['src']

            # --- FALLBACKS: JSON-LD, meta tags, etc. ---
            json_ld_data = self._extract_json_ld(soup)
            for ld in json_ld_data:
                if isinstance(ld, dict):
                    if ld.get('@type') == 'Recipe':
                        if not recipe_data['Title']:
                            recipe_data['Title'] = ld.get('name', '')
                        if not recipe_data['Image']:
                            if 'image' in ld:
                                if isinstance(ld['image'], list) and ld['image']:
                                    recipe_data['Image'] = ld['image'][0]
                                elif isinstance(ld['image'], dict) and 'url' in ld['image']:
                                    recipe_data['Image'] = ld['image']['url']
                                elif isinstance(ld['image'], str):
                                    recipe_data['Image'] = ld['image']
                        if not recipe_data['Description']:
                            recipe_data['Description'] = ld.get('description', '')
                            if not recipe_data['Description'] and 'about' in ld:
                                recipe_data['Description'] = ld['about']
                            if not recipe_data['Description'] and 'articleBody' in ld:
                                recipe_data['Description'] = ld['articleBody']
                        # Dietary requirements
                        dietary_requirements = []
                        if 'recipeCategory' in ld:
                            if isinstance(ld['recipeCategory'], list):
                                dietary_requirements.extend(ld['recipeCategory'])
                            elif isinstance(ld['recipeCategory'], str):
                                dietary_requirements.append(ld['recipeCategory'])
                        if 'keywords' in ld:
                            keywords = ld['keywords']
                            if isinstance(keywords, str):
                                dietary_requirements.extend([k.strip() for k in keywords.split(',')])
                        if dietary_requirements:
                            recipe_data['Dietary Requirements'] = ', '.join(sorted(set(dietary_requirements)))
                    elif ld.get('@type') == 'Person':
                        if not recipe_data['Chef Name']:
                            recipe_data['Chef Name'] = ld.get('name', '')
                        if not recipe_data['Chef Image']:
                            if 'image' in ld:
                                if isinstance(ld['image'], dict) and 'url' in ld['image']:
                                    recipe_data['Chef Image'] = ld['image']['url']
                                elif isinstance(ld['image'], str):
                                    recipe_data['Chef Image'] = ld['image']

            # Fallback for recipe image (meta tag)
            if not recipe_data['Image']:
                og_image = soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    recipe_data['Image'] = og_image['content']

            # Clean up image URLs
            recipe_data['Image'] = self.format_image_url(self.strip_cropping_from_url(recipe_data['Image']))
            recipe_data['Chef Image'] = self.format_image_url(self.strip_cropping_from_url(recipe_data['Chef Image']))

            # Default Chef Name and Chef Image if missing
            if not recipe_data['Chef Name']:
                recipe_data['Chef Name'] = 'Mob'
            if not recipe_data['Chef Image']:
                # Use the same Mob profile image as in row 861
                recipe_data['Chef Image'] = 'https://images.weserv.nl/?url=https://files.mob-cdn.co.uk/files/PROFILE-ICONS_BLACK-2.png?mtime=1702924115&w=640&h=640&fit=cover&q=75&output=jpg&sharp=1&af=&il='

            # Skip if essential data is missing
            if not recipe_data['Title'] or not recipe_data['Image']:
                logging.warning(f"Skipping recipe due to missing essential data: {recipe_url}")
                return None

            return recipe_data

        except Exception as e:
            logging.error(f"Error scraping recipe {recipe_url}: {str(e)}")
            return None

    def save_to_csv(self, recipe_data, output_file='mob_recipes_local.csv'):
        """Save recipe data to CSV file, replacing any existing entry with the same Title."""
        try:
            fieldnames = ['Image', 'Title', 'Time', 'Chef Name', 'Chef Image', 'Description', 'Dietary Requirements']
            rows = []
            found = False
            # Read existing rows if file exists
            if os.path.exists(output_file):
                with open(output_file, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row['Title'] == recipe_data['Title']:
                            rows.append(recipe_data)
                            found = True
                        else:
                            rows.append(row)
            if not found:
                rows.append(recipe_data)
            # Write all rows back to the CSV
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(rows)
            logging.info(f"Successfully saved recipe: {recipe_data['Title']}")
            return True
        except Exception as e:
            logging.error(f"Error saving recipe to CSV: {str(e)}")
            return False

def main():
    scraper = IndividualRecipeScraper()
    urls = [
        "https://www.mob.co.uk/recipes/sweet-soy-cod-with-sriracha-broccoli",
        "https://www.mob.co.uk/recipes/sesame-crusted-cod-and-creamy-chilli-oil-chickpeas",
        "https://www.mob.co.uk/recipes/salmon-pasta-salad",
        "https://www.mob.co.uk/recipes/salmon-with-kimchi-tahini-noodles",
        "https://www.mob.co.uk/recipes/korean-marinated-eggs",
        "https://www.mob.co.uk/recipes/salmon-with-caramelised-onion-rice-shaved-broccoli-salad",
        "https://www.mob.co.uk/recipes/hot-smoked-salmon-bowl-with-miso-lemon-vinaigrette",
        "https://www.mob.co.uk/recipes/salmon-with-crispy-bagel-seasoning-new-potatoes-pickled-onions",
        "https://www.mob.co.uk/recipes/baked-tuna-egg-mayo-on-japanese-rice-with-teriyaki-sauce"
    ]
    for url in urls:
        recipe_data = scraper.scrape_recipe(url)
        if recipe_data:
            scraper.save_to_csv(recipe_data)
            print(f"Successfully scraped and saved recipe: {recipe_data['Title']}")
        else:
            print(f"Failed to scrape recipe: {url}")

if __name__ == "__main__":
    main() 