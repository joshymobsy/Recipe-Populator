import requests
from bs4 import BeautifulSoup
import csv
import re
import time
import json
from urllib.parse import urljoin
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

class MobScraper:
    def __init__(self):
        self.base_url = "https://www.mob.co.uk"
        self.collection_url = f"{self.base_url}/recipes/collections/high-protein-midweek-meals"
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
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
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

    def backup_existing_csv(self):
        """Create a backup of the existing CSV file"""
        if os.path.exists('mob_recipes_local.csv'):
            try:
                with open('mob_recipes_local.csv', 'r', encoding='utf-8') as src:
                    with open(self.backup_file, 'w', encoding='utf-8') as dst:
                        dst.write(src.read())
                logging.info(f"Created backup at {self.backup_file}")
            except Exception as e:
                logging.error(f"Failed to create backup: {str(e)}")

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
        # Pattern matches e.g. /_1200x630_crop_center-center_82_none/ or /recipes/2024/12/_1200x630_crop_center-center_82_none/
        return re.sub(r'/(_[0-9]+x[0-9]+_crop_[^/]+/)', '/', url)

    def extract_recipe_data(self, card, collection_json_ld):
        """Extract data from a recipe card and fetch details from its individual page"""
        recipe_data = {}
        try:
            # Extract data from the card on the collection page
            recipe_a = card.find('a', href=re.compile(r'^/recipes/'))
            if not recipe_a:
                raise ValueError("Recipe link not found on collection page")

            recipe_url_path = recipe_a['href']
            recipe_url = urljoin(self.base_url, recipe_url_path)

            # Find title - look for text in recipe card
            title = card.find('h3', class_=re.compile(r'font-body')).text.strip() if card.find('h3', class_=re.compile(r'font-body')) else ''

            # Find time - look for div with time class
            time_div = card.find('div', class_=re.compile(r'text-zinc-500'))
            time_text = self.clean_time_format(time_div.get_text(strip=True) if time_div else '')

            # Find chef info
            chef_a = card.find('a', href=re.compile(r'^/chefs/'))
            chef_name = chef_a.find('div', class_=re.compile(r'whitespace-nowrap')).text.strip() if chef_a else ''
            chef_url_path = chef_a['href'] if chef_a else ''

            # Try to get recipe image from card first
            recipe_img = ''
            img_tag = card.find('img')
            if img_tag and img_tag.get('src'):
                recipe_img = img_tag['src']
            elif img_tag and img_tag.get('data-src'):
                recipe_img = img_tag['data-src']

            # Visit individual recipe page
            logging.info(f"Visiting individual recipe page: {recipe_url}")
            individual_recipe_html = self.make_request(recipe_url)
            individual_recipe_soup = BeautifulSoup(individual_recipe_html, 'html.parser')
            individual_json_ld = self._extract_json_ld(individual_recipe_soup)

            description = ''
            dietary_requirements = []
            chef_img = ''

            # Extract recipe details from JSON-LD
            for ld in individual_json_ld:
                if isinstance(ld, dict):
                    # Recipe data
                    if ld.get('@type') == 'Recipe':
                        # Get recipe image if not found in card
                        if not recipe_img and 'image' in ld:
                            if isinstance(ld['image'], list) and ld['image']:
                                recipe_img = ld['image'][0]
                            elif isinstance(ld['image'], dict) and 'url' in ld['image']:
                                recipe_img = ld['image']['url']
                            elif isinstance(ld['image'], str):
                                recipe_img = ld['image']

                        # Get description
                        description = ld.get('description', '')
                        if not description and 'about' in ld:
                            description = ld['about']

                        # Get dietary requirements
                        if 'recipeCategory' in ld:
                            if isinstance(ld['recipeCategory'], list):
                                dietary_requirements.extend(ld['recipeCategory'])
                            elif isinstance(ld['recipeCategory'], str):
                                dietary_requirements.append(ld['recipeCategory'])

                        # Additional dietary info from keywords
                        if 'keywords' in ld:
                            keywords = ld['keywords']
                            if isinstance(keywords, str):
                                dietary_requirements.extend([k.strip() for k in keywords.split(',')])

                        # Additional dietary info from suitableForDiet
                        if 'suitableForDiet' in ld:
                            if isinstance(ld['suitableForDiet'], list):
                                dietary_requirements.extend(ld['suitableForDiet'])
                            elif isinstance(ld['suitableForDiet'], str):
                                dietary_requirements.append(ld['suitableForDiet'])

                    # Chef data
                    elif ld.get('@type') == 'Person' and ld.get('name') == chef_name:
                        if 'image' in ld:
                            if isinstance(ld['image'], dict) and 'url' in ld['image']:
                                chef_img = ld['image']['url']
                            elif isinstance(ld['image'], str):
                                chef_img = ld['image']

            # Fallback for recipe image - try meta tags
            if not recipe_img:
                og_image = individual_recipe_soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    recipe_img = og_image['content']

            # Fallback for chef image
            if not chef_img and chef_url_path:
                chef_page_url = urljoin(self.base_url, chef_url_path)
                logging.info(f"Visiting chef page for fallback: {chef_page_url}")
                chef_page_html = self.make_request(chef_page_url)
                chef_page_soup = BeautifulSoup(chef_page_html, 'html.parser')
                
                # Try to find chef image in meta tags first
                og_image = chef_page_soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    chef_img = og_image['content']
                else:
                    # Fallback to JSON-LD
                    chef_json_ld = self._extract_json_ld(chef_page_soup)
                    for ld in chef_json_ld:
                        if isinstance(ld, dict) and ld.get('@type') == 'Person' and ld.get('name') == chef_name:
                            if 'image' in ld:
                                if isinstance(ld['image'], dict) and 'url' in ld['image']:
                                    chef_img = ld['image']['url']
                                elif isinstance(ld['image'], str):
                                    chef_img = ld['image']

            # Clean up dietary requirements
            dietary_requirements = list(set([r.strip() for r in dietary_requirements if r.strip()]))
            dietary_requirements.sort()

            # After all image extraction logic, clean up the URLs
            recipe_img = self.strip_cropping_from_url(recipe_img)
            chef_img = self.strip_cropping_from_url(chef_img)

            recipe_data = {
                'Image': self.format_image_url(recipe_img),
                'Title': title,
                'Time': time_text,
                'Chef Image': self.format_image_url(chef_img),
                'Chef Name': chef_name,
                'Description': description,
                'Dietary Requirements': ', '.join(dietary_requirements)
            }

            return recipe_data
        except Exception as e:
            logging.error(f"Error extracting recipe data: {e}")
            return None

    def format_image_url(self, url):
        """Format image URL for use with images.weserv.nl"""
        if not url:
            return ''
        if not url.startswith('https://images.weserv.nl'):
            if 'mob-cdn.co.uk' in url:
                return f"https://images.weserv.nl/?url={url}"
            elif url.startswith('//'):
                return f"https://images.weserv.nl/?url=https:{url}"
            elif url.startswith('/'):
                return f"https://images.weserv.nl/?url={self.base_url}{url}"
        return url

    def scrape_recipes(self):
        """Main scraping function"""
        try:
            # Get the collection page content
            html_content = self.make_request(self.collection_url)
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find all recipe cards - more flexible selector
            cards = soup.find_all('div', class_=re.compile(r'overflow-hidden.*rounded-2xl.*bg-white'))
            
            if not cards:
                logging.warning("No recipe cards found. Trying alternative selector...")
                cards = soup.find_all('div', class_=re.compile(r'overflow-hidden.*rounded-2xl'))
            
            if not cards:
                raise ValueError("No recipe cards found with any selector")
            
            recipes = []
            for card in cards:
                recipe_data = self.extract_recipe_data(card, [])
                if recipe_data:
                    recipes.append(recipe_data)
                    logging.info(f"Scraped: {recipe_data['Title']}")
            
            if not recipes:
                raise ValueError("No recipes were successfully scraped")
            
            # Write to CSV
            with open('mob_recipes_local.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['Image', 'Title', 'Time', 'Chef Name', 'Chef Image', 'Description', 'Dietary Requirements'])
                writer.writeheader()
                writer.writerows(recipes)
            
            logging.info(f"Successfully scraped {len(recipes)} recipes")
            return True
            
        except Exception as e:
            logging.error(f"Error in main scraping function: {str(e)}")
            return False

def main():
    scraper = MobScraper()
    success = scraper.scrape_recipes()
    
    if success:
        logging.info("Scraping completed successfully")
    else:
        logging.error("Scraping failed")
        if os.path.exists(scraper.backup_file):
            try:
                os.replace(scraper.backup_file, 'mob_recipes_local.csv')
                logging.info("Restored from backup")
            except Exception as e:
                logging.error(f"Failed to restore from backup: {str(e)}")

if __name__ == "__main__":
    main() 