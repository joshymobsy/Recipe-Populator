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
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                # Explicitly wait for an image element within a recipe card to ensure content is loaded
                page.wait_for_selector('div[class*="overflow-hidden"][class*="rounded-2xl"] img[src^="http"], div[class*="overflow-hidden"][class*="rounded-2xl"] img[data-src^="http"]', timeout=60000)
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

    def extract_recipe_data(self, card, collection_json_ld, default_dietary_category=None):
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
            title_a = card.find('a', class_=re.compile(r'font-body'), href=re.compile(r'^/recipes/'))
            title = title_a.text.strip() if title_a else ''
            if not title:
                logging.warning(f"Title not found for recipe card: {recipe_a['href'] if recipe_a else 'N/A'}")
                return None

            # Find time - look for div with time class
            time_div = card.find('div', class_=re.compile(r'text-zinc-500'))
            time_text = self.clean_time_format(time_div.get_text(strip=True) if time_div else '')

            # Find chef info
            chef_a = card.find('a', href=re.compile(r'^/chefs/'))
            chef_name = chef_a.find('div', class_=re.compile(r'whitespace-nowrap')).text.strip() if chef_a else ''
            chef_url_path = chef_a['href'] if chef_a else ''

            # Visit individual recipe page FIRST to get the high-quality image and other details
            logging.info(f"Visiting individual recipe page: {recipe_url}")
            individual_recipe_html = self.make_request(recipe_url)
            individual_recipe_soup = BeautifulSoup(individual_recipe_html, 'html.parser')
            individual_json_ld = self._extract_json_ld(individual_recipe_soup)

            recipe_img = ''
            description = ''
            dietary_requirements = []
            chef_img = ''

            # Extract recipe details from JSON-LD first
            for ld in individual_json_ld:
                if isinstance(ld, dict):
                    # Recipe data
                    if ld.get('@type') == 'Recipe':
                        # Get recipe image from JSON-LD
                        if 'image' in ld:
                            if isinstance(ld['image'], list) and ld['image']:
                                recipe_img = ld['image'][0]
                            elif isinstance(ld['image'], dict) and 'url' in ld['image']:
                                recipe_img = ld['image']['url']
                            elif isinstance(ld['image'], str):
                                recipe_img = ld['image']
                            else:
                                logging.debug(f"No 'image' found in Recipe JSON-LD (neither dict with url nor string) for {recipe_url}")
                        else:
                            logging.debug(f"No 'image' key found in Recipe JSON-LD for {recipe_url}")

                        # Get description
                        description = ld.get('description', '')
                        if not description and 'about' in ld:
                            description = ld['about']
                        # Try extracting description from articleBody if available
                        if not description and 'articleBody' in ld:
                            description = ld['articleBody']
                        if not description:
                            logging.debug(f"No description found in JSON-LD (description, about, articleBody) for {recipe_url}")

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
                        
                        # Check for nutrition/dietary restrictions within JSON-LD
                        if 'nutrition' in ld and isinstance(ld['nutrition'], dict):
                            nutrition_data = ld['nutrition']
                            if 'suitableForDiet' in nutrition_data:
                                if isinstance(nutrition_data['suitableForDiet'], list):
                                    dietary_requirements.extend(nutrition_data['suitableForDiet'])
                                elif isinstance(nutrition_data['suitableForDiet'], str):
                                    dietary_requirements.append(nutrition_data['suitableForDiet'])

                    # Chef data
                    elif ld.get('@type') == 'Person':
                        if ld.get('name') == chef_name:
                            if 'image' in ld:
                                if isinstance(ld['image'], dict) and 'url' in ld['image']:
                                    chef_img = ld['image']['url']
                                elif isinstance(ld['image'], str):
                                    chef_img = ld['image']
                                else:
                                    logging.debug(f"Chef image fallback (JSON-LD) failed: no 'image' found (neither dict with url nor string) for {chef_name} for {recipe_url}")
                            else:
                                logging.debug(f"Chef image fallback (JSON-LD) failed: 'image' key not found for {chef_name} for {recipe_url}")
                        else:
                            logging.debug(f"Chef data: Person type but name mismatch for {chef_name} for {recipe_url}")

            # Fallback for description - try to find it in the specific div based on screenshot
            if not description:
                logging.debug(f"Attempting description fallback for {recipe_url}")
                description_div_outer = individual_recipe_soup.find('div', class_=re.compile(r'body-text-sm.*max-w-prose'))
                if description_div_outer:
                    description_div_inner = description_div_outer.find('div', class_=re.compile(r'line-clamp-2|md:line-clamp-5'))
                    if description_div_inner:
                        description = description_div_inner.get_text(strip=True)
                    else:
                        logging.debug(f"Description fallback failed: inner div not found for {recipe_url}")
                else:
                    logging.debug(f"Description fallback failed: outer div not found for {recipe_url}")

            # Fallback for recipe image - try meta tags on individual page
            if not recipe_img:
                logging.debug(f"Attempting recipe image fallback (meta tags) for {recipe_url}")
                og_image = individual_recipe_soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    recipe_img = og_image['content']
                else:
                    logging.debug(f"Recipe image fallback (meta tags) failed for {recipe_url}")
            
            # Fallback for recipe image - try from card if still not found (least preferred)
            if not recipe_img:
                logging.debug(f"Attempting recipe image fallback (card img tag) for {recipe_url}")
                img_tag = card.find('img')
                if img_tag and img_tag.get('src'):
                    recipe_img = img_tag['src']
                elif img_tag and img_tag.get('data-src'):
                    recipe_img = img_tag['data-src']
                else:
                    logging.debug(f"Recipe image fallback (card img tag) failed for {recipe_url}")

            # Fallback for chef image
            if not chef_img and chef_url_path:
                logging.debug(f"Attempting chef image fallback for {recipe_url}")
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
                        if isinstance(ld, dict) and ld.get('@type') == 'Person':
                            if ld.get('name') == chef_name:
                                if 'image' in ld:
                                    if isinstance(ld['image'], dict) and 'url' in ld['image']:
                                        chef_img = ld['image']['url']
                                    elif isinstance(ld['image'], str):
                                        chef_img = ld['image']
                                    else:
                                        logging.debug(f"Chef image fallback (JSON-LD) failed: no 'image' found (neither dict with url nor string) for {chef_name} for {recipe_url}")
                                else:
                                    logging.debug(f"Chef image fallback (JSON-LD) failed: 'image' key not found for {chef_name} for {recipe_url}")
                            else:
                                logging.debug(f"Chef data: Person type but name mismatch for {chef_name} for {recipe_url}")
            else:
                logging.debug(f"No chef image found and no chef_url_path for {recipe_url}")

            # Clean up dietary requirements
            dietary_requirements = list(set([r.strip() for r in dietary_requirements if r.strip()]))
            dietary_requirements.sort()
            
            # If no dietary requirements found and a default category is provided, set it
            if not dietary_requirements and default_dietary_category:
                logging.debug(f"Applying default dietary category '{default_dietary_category}' for {recipe_url}")
                dietary_output = default_dietary_category
            else:
                dietary_output = ', '.join(dietary_requirements) if dietary_requirements else "None"
                if not dietary_requirements:
                    logging.debug(f"No dietary requirements found for {recipe_url}, setting to 'None'")

            # After all image extraction logic, clean up the URLs
            recipe_img = self.strip_cropping_from_url(recipe_img)
            chef_img = self.strip_cropping_from_url(chef_img)

            # If the recipe has a placeholder image and an empty description, skip it
            if recipe_img == "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" and not description:
                logging.warning(f"Skipping recipe '{title}' (URL: {recipe_url}) due to placeholder image and empty description.")
                return None

            recipe_data = {
                'Image': self.format_image_url(recipe_img) if recipe_img else "",
                'Title': title,
                'Time': time_text,
                'Chef Image': self.format_image_url(chef_img) if chef_img else "",
                'Chef Name': chef_name,
                'Description': description,
                'Dietary Requirements': dietary_output
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

    def scrape_recipes(self, collection_url, default_dietary_category=None):
        """Main scraping function"""
        try:
            # Get the collection page content
            html_content = self.make_request(collection_url)
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
                recipe_data = self.extract_recipe_data(card, [], default_dietary_category)
                if recipe_data:
                    recipes.append(recipe_data)
                    logging.info(f"Scraped: {recipe_data['Title']}")
            
            if not recipes:
                raise ValueError("No recipes were successfully scraped")
            
            # Write to CSV in append mode
            file_exists = os.path.exists('mob_recipes_local.csv')
            with open('mob_recipes_local.csv', 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['Image', 'Title', 'Time', 'Chef Name', 'Chef Image', 'Description', 'Dietary Requirements'], quoting=csv.QUOTE_ALL)
                
                # Only write header if file is new
                if not file_exists:
                    writer.writeheader()

                for recipe in recipes:
                    writer.writerow(recipe)
            
            logging.info(f"Successfully scraped {len(recipes)} recipes")
            return True
            
        except Exception as e:
            logging.error(f"Error in main scraping function: {str(e)}")
            return False

def main():
    scraper = MobScraper()
    
    # Scrape from the vegetarian dinners collection page
    vegetarian_collection_url = "https://www.mob.co.uk/recipes/collections/vegetarian-dinners"
    success = scraper.scrape_recipes(vegetarian_collection_url, default_dietary_category="Vegetarian")
    
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