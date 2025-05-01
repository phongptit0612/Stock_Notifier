import requests
from bs4 import BeautifulSoup
import json
import time
import logging
import os
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("stock_monitor.log")
    ]
)
logger = logging.getLogger(__name__)

# Constants
URL = "https://vulcanvalues.com/grow-a-garden/stock"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1367372208904605729/pD_WrudJNhUrQBLKo4nnKfwUSlyYnqzjkfX-IxganPwEM2PUaoeChepRVMOrwso9wDj3"
CHECK_INTERVAL = 10  # seconds

class StockMonitor:
    def __init__(self, url, webhook_url, check_interval=10):
        """
        Initialize the stock monitor.
        
        Args:
            url (str): URL to monitor for stock changes
            webhook_url (str): Discord webhook URL for notifications
            check_interval (int): Interval between checks in seconds
        """
        self.url = url
        self.webhook_url = webhook_url
        self.check_interval = check_interval
        self.previous_stock = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        logger.info(f"Stock monitor initialized. URL: {url}, Check interval: {check_interval}s")
    
    def get_current_stock(self):
        """
        Fetch and parse the current stock information from the website.
        Specifically optimized for Vulcan Values Grow A Garden stock page.
        
        Returns:
            dict: Parsed stock information with categories for gears and crops
        """
        try:
            logger.debug(f"Fetching stock information from {self.url}")
            response = requests.get(self.url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Initialize stock info with separate categories
            stock_info = {
                "gears": {},
                "crops": {},
                "easter": {},
                "other_items": {}
            }
            
            # Find all section headers (h2 elements)
            headers = soup.find_all('h2')
            
            # Process each section based on its header
            for header in headers:
                header_text = header.get_text(strip=True)
                
                # Find the parent div of the header, which should contain the entire section
                section_div = header.find_parent('div')
                if not section_div:
                    continue
                
                # Get the countdown text from the section
                countdown_text = ""
                countdown_p = section_div.find('p', class_='text-yellow-400')
                if countdown_p:
                    countdown_text = countdown_p.get_text(strip=True)
                
                # Find all list items in this section
                items = section_div.find_all('li')
                
                # Determine which category this section belongs to
                category_key = "other_items"  # Default category
                
                if "GEAR STOCK" in header_text:
                    category_key = "gears"
                    # Add the update countdown information
                    stock_info["gears"]["updates_in"] = countdown_text
                elif "SEEDS STOCK" in header_text:
                    category_key = "crops"
                    # Add the update countdown information
                    stock_info["crops"]["updates_in"] = countdown_text
                elif "EASTER STOCK" in header_text:
                    category_key = "easter"
                    # Add the update countdown information
                    stock_info["easter"]["updates_in"] = countdown_text
                
                # Process all items in this section
                for item in items:
                    # Get the item's text content
                    item_text = item.get_text(strip=True)
                    
                    # Extract the item name and quantity
                    # Expected format: "Item Name x5" or similar
                    parts = item_text.split('x')
                    if len(parts) > 1:
                        name = parts[0].strip()
                        quantity = "x" + parts[1].strip()
                        stock_info[category_key][name] = quantity
                    else:
                        # If we can't parse the quantity format, just use the text as is
                        stock_info[category_key][item_text] = "In Stock"
            
            # If we haven't found any structured information, try a more general approach
            if not any(items for category, items in stock_info.items() if items and category != "other_items"):
                logger.warning("Could not parse structured information, trying alternate methods")
                
                # Look for any list items on the page
                all_items = soup.find_all('li', class_='bg-gray-900 p-3 rounded-md border border-gray-700 text-white font-medium flex items-center space-x-3')
                
                for item in all_items:
                    # Try to get the image to identify the item
                    img = item.find('img')
                    item_name = img.get('alt') if img and img.get('alt') else "Unknown Item"
                    
                    # Get the item's text for quantity
                    item_text = item.get_text(strip=True)
                    quantity_match = None
                    if 'x' in item_text:
                        parts = item_text.split('x')
                        if len(parts) > 1 and parts[1].strip().isdigit():
                            quantity_match = f"x{parts[1].strip()}"
                    
                    # If we couldn't extract a quantity, just mark as in stock
                    quantity = quantity_match if quantity_match else "In Stock"
                    
                    # Try to categorize based on item name
                    if any(keyword in item_name.lower() for keyword in ['hoe', 'rake', 'shovel', 'tool', 'gear']):
                        stock_info['gears'][item_name] = quantity
                    elif any(keyword in item_name.lower() for keyword in ['carrot', 'tomato', 'strawberry', 'blueberry', 'seed', 'plant']):
                        stock_info['crops'][item_name] = quantity
                    elif any(keyword in item_name.lower() for keyword in ['egg', 'bunny', 'easter']):
                        stock_info['easter'][item_name] = quantity
                    else:
                        stock_info['other_items'][item_name] = quantity
            
            # Final fallback: if we still couldn't find any structured information
            if not any(category for category, items in stock_info.items() if items and category != "other_items"):
                logger.warning("Could not parse structured information, extracting general content")
                content = soup.get_text(strip=True)
                # Limit the size to prevent sending extremely large messages
                stock_info = {"general_content": content[:1500] + "..." if len(content) > 1500 else content}
            
            logger.debug(f"Successfully parsed stock information: {len(stock_info)} items found")
            return stock_info
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching stock information: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing stock information: {e}")
            return None
    
    def stock_has_changed(self, current_stock):
        """
        Check if the stock information has changed since the last check.
        
        Args:
            current_stock (dict): Current stock information
            
        Returns:
            bool: True if stock has changed, False otherwise
        """
        if self.previous_stock is None:
            logger.info("First check - establishing baseline stock information")
            return True
        
        # If we couldn't fetch current stock, don't consider it a change
        if current_stock is None:
            return False
        
        # Check if the dictionaries are different
        if self.previous_stock != current_stock:
            logger.info("Stock information has changed")
            return True
        
        logger.debug("No change in stock information detected")
        return False
    
    def send_discord_notification(self, stock_info):
        """
        Send a notification to Discord with the current stock information.
        
        Args:
            stock_info (dict): Stock information to include in the notification
        """
        try:
            # Create a formatted message
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Define product icons
            crop_icons = {
                "Carrot": "🥕",
                "Strawberry": "🍓",
                "Blueberry": "🫐",
                "Orange": "🍊",
                "Tulip": "🌷",
                "Orange Tulip": "🌷",
                "Tomato": "🍅",
                "Corn": "🌽",
                "Daffodil": "💐",
                "Watermelon": "🍉",
                "Watermelin": "🍉",  # Typo handling
                "Pumpkin": "🎃",
                "Apple": "🍎",
                "Bamboo": "🎋",
                "Coconut": "🥥",
                "Cactus": "🌵",
                "Dragon Fruit": "🐉🍎",
                "Mango": "🥭",
                "Grape": "🍇",
                "Mushroom": "🍄"
            }
            
            gear_icons = {
                "Watering Can": "💧",
                "Trowel": "🔨",
                "Basic Sprinkler": "💦",
                "Advanced Sprinkler": "🌧️",
                "Lightning Rod": "⚡",
                "Godly Sprinkler": "✨",
                "Master Sprinkler": "🌈"
            }
            
            # Start building the message with the box format
            message_content = f"# Stock Update at {current_time} #\n\n"
            
            if not stock_info:
                message_content += "Could not retrieve stock information."
            elif "general_content" in stock_info:
                # Handle completely unstructured content
                message_content += f"General Stock Information:\n{stock_info['general_content']}"
            else:
                # Format categorized items
                # Gears section
                if stock_info.get("gears") and any(k != "updates_in" for k in stock_info["gears"]):
                    message_content += "🛠️ GARDEN GEARS/TOOLS:\n\n"
                    
                    # Show all gear items except metadata fields
                    for product, availability in stock_info["gears"].items():
                        if product != "updates_in" and not product.startswith("content_"):
                            # Get appropriate icon for this gear
                            icon = ""
                            for gear_name, gear_icon in gear_icons.items():
                                if gear_name.lower() in product.lower() or product.lower() in gear_name.lower():
                                    icon = gear_icon + " "
                                    break
                            if not icon:  # Default icon if no specific match
                                icon = "🔧 "
                            
                            message_content += f"{icon}{product}: {availability}\n"
                    
                    message_content += "\n"
                
                # Crops/Seeds section
                if stock_info.get("crops") and any(k != "updates_in" for k in stock_info["crops"]):
                    message_content += "🌱 CROPS/PLANTS/SEEDS:\n\n"
                    
                    # Show all crop items except metadata fields
                    for product, availability in stock_info["crops"].items():
                        if product != "updates_in" and not product.startswith("content_"):
                            # Get appropriate icon for this crop
                            icon = ""
                            for crop_name, crop_icon in crop_icons.items():
                                if crop_name.lower() in product.lower() or product.lower() in crop_name.lower():
                                    icon = crop_icon + " "
                                    break
                            if not icon:  # Default icon if no specific match
                                icon = "🌱 "
                            
                            message_content += f"{icon}{product}: {availability}\n"
                    
                    message_content += "\n"
                
                # Easter section
                if stock_info.get("easter") and any(k != "updates_in" for k in stock_info["easter"]):
                    message_content += "🐰 EASTER ITEMS:\n\n"
                    
                    # Show all easter items except metadata fields
                    for product, availability in stock_info["easter"].items():
                        if product != "updates_in":
                            message_content += f"🥚 {product}: {availability}\n"
                    
                    message_content += "\n"
                
                # Other items section
                if stock_info.get("other_items"):
                    message_content += "📦 OTHER ITEMS:\n\n"
                    
                    for product, availability in stock_info["other_items"].items():
                        message_content += f"📦 {product}: {availability}\n"
            
            # Put all the content in a single box using Discord's code block
            message = f"```md\n{message_content}```"
            
            # Prepare and send the payload
            payload = {
                "content": message,
                "username": "Vulcan Values Stock Monitor"
            }
            
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            response.raise_for_status()
            logger.info("Discord notification sent successfully")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending Discord notification: {e}")
        except Exception as e:
            logger.error(f"Unexpected error while sending Discord notification: {e}")
    
    def run(self):
        """
        Run the stock monitor continuously.
        """
        logger.info("Starting stock monitoring loop")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while True:
            try:
                # Get current stock information
                current_stock = self.get_current_stock()
                
                # Check if it's different from the previous stock
                if self.stock_has_changed(current_stock):
                    # Send a notification with the current stock
                    self.send_discord_notification(current_stock)
                    # Update the previous stock
                    self.previous_stock = current_stock
                
                # Reset error counter on successful execution
                consecutive_errors = 0
                
                # Wait before checking again
                time.sleep(self.check_interval)
                
            except Exception as e:
                # Increment error counter
                consecutive_errors += 1
                logger.error(f"Error in monitoring loop: {e}")
                
                # If we've had too many consecutive errors, increase the wait time
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"Too many consecutive errors ({consecutive_errors}). Increasing wait time.")
                    time.sleep(self.check_interval * 3)  # Wait longer before retrying
                else:
                    time.sleep(self.check_interval)


if __name__ == "__main__":
    # Get webhook URL from environment if available
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", DISCORD_WEBHOOK_URL)
    
    # Create and run the stock monitor
    monitor = StockMonitor(URL, webhook_url, CHECK_INTERVAL)
    
    while True:
        try:
            logger.info("Starting stock monitor")
            monitor.run()
        except KeyboardInterrupt:
            logger.info("Stock monitor stopped by user")
            break
        except Exception as e:
            logger.critical(f"Stock monitor crashed with error: {e}")
            logger.info("Restarting stock monitor in 30 seconds...")
            time.sleep(30)  # Wait before restarting
