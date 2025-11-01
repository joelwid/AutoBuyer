"""
Selenium automation for adding products to Digitec/Galaxus cart
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import os


def make_driver(headless: bool = True):
    """Create a Selenium WebDriver instance"""
    SELENIUM_URL = os.getenv("SELENIUM_URL", "")
    options = Options()
    
    # Add user agent to avoid detection
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    options.add_argument(f'user-agent={user_agent}')
    
    if headless:
        options.add_argument("--headless=new")
    
    # Anti-detection and stability options
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--ignore-certificate-errors")
    
    # Disable HTTP/2 to avoid ERR_HTTP2_PROTOCOL_ERROR
    options.add_argument("--disable-http2")
    
    options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_experimental_option("prefs", {
        "profile.default_content_setting_values.notifications": 2,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    })
    
    # Try to use remote Selenium if URL is provided (Docker environment)
    # Otherwise, use local Chrome driver
    try:
        if SELENIUM_URL and SELENIUM_URL.startswith("http"):
            print(f"Attempting to connect to remote Selenium: {SELENIUM_URL}")
            return webdriver.Remote(command_executor=SELENIUM_URL, options=options)
    except Exception as e:
        print(f"Remote Selenium not available: {e}, falling back to local Chrome")
    
    # Use local Chrome driver
    try:
        print("Creating local Chrome driver...")
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        print("Chrome driver created successfully")
        return driver
    except Exception as e:
        print(f"Failed to create Chrome driver with webdriver_manager: {e}")
        # Last resort: try default Chrome driver
        try:
            driver = webdriver.Chrome(options=options)
            print("Chrome driver created using default method")
            return driver
        except Exception as e2:
            print(f"Failed to create Chrome driver: {e2}")
            raise


def login_to_digitec(driver, email: str, password: str) -> bool:
    """
    Log into Digitec/Galaxus account
    
    Args:
        driver: Selenium WebDriver instance
        email: Account email
        password: Account password
    
    Returns:
        bool: True if login successful, False otherwise
    """
    try:
        # Navigate to login page
        driver.get("https://id.digitecgalaxus.ch/n/p/22/de")
        wait = WebDriverWait(driver, 10)
        
        # Email field
        email_field = wait.until(EC.presence_of_element_located((By.ID, "email")))
        email_field.send_keys(email)
        
        # Click Next
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(1)
        
        # Password field
        password_field = wait.until(EC.presence_of_element_located((By.ID, "password")))
        password_field.send_keys(password)
        
        # Click login
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        time.sleep(3)
        
        # Check if logged in
        return "id.digitecgalaxus.ch" not in driver.current_url
        
    except Exception as e:
        print(f"Login failed: {e}")
        return False


def add_product_to_cart(product_url: str, email: str = None, password: str = None) -> dict:
    """
    Add a product to the Digitec/Galaxus cart
    
    Args:
        product_url: URL of the product to add
        email: Digitec account email (optional, for login)
        password: Digitec account password (optional, for login)
    
    Returns:
        dict: {"success": bool, "message": str, "cart_url": str}
    """
    driver = None
    try:
        print("=" * 50)
        print("Starting add_product_to_cart")
        print(f"URL: {product_url}")
        print("=" * 50)
        
        driver = make_driver(headless=True)  # Headless mode - browser runs in background
        print("Driver created successfully")
        
        # Login if credentials provided
        if email and password:
            print("Attempting login...")
            login_success = login_to_digitec(driver, email, password)
            if not login_success:
                print("Login failed or skipped, continuing anyway...")
        
        # Navigate to product page
        print(f"Navigating to: {product_url}")
        driver.get(product_url)
        wait = WebDriverWait(driver, 15)
        
        # Wait for page to load - look for any button to ensure page is interactive
        print("Waiting for page to load...")
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "button")))
            print("Page loaded, buttons detected")
        except TimeoutException:
            print("Timeout waiting for page to load")
        
        # Additional wait to ensure JavaScript has executed
        time.sleep(2)  # Reduced from 3
        
        print(f"Current URL: {driver.current_url}")
        print(f"Page title: {driver.title}")
        
        # Common selectors for "Add to Cart" button on Digitec/Galaxus
        add_to_cart_selectors = [
            (By.ID, "addToCartButton"),  # The button has this ID
            (By.CSS_SELECTOR, "button[data-test='addToCartButton']"),
            (By.XPATH, "//button[contains(text(), 'In den Warenkorb legen')]"),  # Exact text match
            (By.XPATH, "//button[contains(text(), 'In den Warenkorb')]"),  # Partial match
            (By.CSS_SELECTOR, "button[aria-label*='Warenkorb']"),
            (By.CSS_SELECTOR, "button[data-cy='add-to-cart']"),
            (By.CSS_SELECTOR, "button.add-to-cart"),
            (By.CSS_SELECTOR, ".productDetail__addToCart button"),
            (By.CSS_SELECTOR, "[data-testid='add-to-cart-button']"),
            (By.XPATH, "//button[contains(text(), 'Warenkorb')]"),
            (By.XPATH, "//button[contains(@class, 'add')]"),
        ]
        
        button_found = False
        for selector_type, selector_value in add_to_cart_selectors:
            try:
                print(f"Trying selector: {selector_type} = {selector_value}")
                add_button = wait.until(
                    EC.element_to_be_clickable((selector_type, selector_value))
                )
                
                # Scroll to button
                driver.execute_script("arguments[0].scrollIntoView(true);", add_button)
                time.sleep(0.5)
                
                # Get button details before clicking
                button_text = add_button.text
                button_aria = add_button.get_attribute("aria-label")
                print(f"Found button - Text: '{button_text}', Aria-label: '{button_aria}'")
                
                # Check if button is enabled/clickable
                is_enabled = add_button.is_enabled()
                is_displayed = add_button.is_displayed()
                print(f"Button state - Enabled: {is_enabled}, Displayed: {is_displayed}")
                
                # Print cookies before clicking
                cookies_before = len(driver.get_cookies())
                print(f"Cookies before click: {cookies_before}")
                
                # Try regular click first
                try:
                    print("Attempting regular click...")
                    add_button.click()
                    print("Regular click executed")
                except Exception as click_error:
                    print(f"Regular click failed: {click_error}, trying JavaScript click...")
                    driver.execute_script("arguments[0].click();", add_button)
                    print("JavaScript click executed")
                
                # Wait a bit and check cookies after
                time.sleep(2)
                cookies_after = len(driver.get_cookies())
                print(f"Cookies after click: {cookies_after}")
                
                if cookies_after > cookies_before:
                    print(f"✅ {cookies_after - cookies_before} new cookie(s) added")
                
                button_found = True
                
                # Wait for cart to update and any animation/popup to appear
                time.sleep(2)  # Reduced from 3
                
                # Check for modals or popups that might have appeared
                try:
                    modals = driver.find_elements(By.CSS_SELECTOR, "[role='dialog'], .modal, [class*='popup']")
                    if modals:
                        print(f"Found {len(modals)} modal(s)/popup(s)")
                        for modal in modals:
                            print(f"Modal text: {modal.text[:200]}")
                except:
                    pass
                
                # Save screenshot after clicking
                driver.save_screenshot("debug_after_cart_click.png")
                print("Screenshot saved after cart click")
                
                # Save page source after click
                with open("debug_after_click_source.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("Page source saved after click")
                
                # Check for success indicators
                try:
                    # Look for common success messages or modals
                    success_indicators = [
                        (By.XPATH, "//*[contains(text(), 'Warenkorb')]"),
                        (By.XPATH, "//*[contains(text(), 'hinzugefügt')]"),
                        (By.XPATH, "//*[contains(text(), 'added')]"),
                        (By.CSS_SELECTOR, "[class*='success']"),
                        (By.CSS_SELECTOR, "[class*='notification']"),
                        (By.CSS_SELECTOR, "[role='alert']")
                    ]
                    
                    for sel_type, sel_val in success_indicators:
                        try:
                            indicator = driver.find_element(sel_type, sel_val)
                            print(f"✅ Found success indicator: {indicator.text[:100]}")
                        except:
                            continue
                except Exception as e:
                    print(f"No obvious success indicators: {e}")
                
                # Instead of navigating to cart, wait longer for the sidebar to load
                time.sleep(2)  # Reduced from 5
                
                # Look for cart sidebar with items
                try:
                    cart_sidebar = driver.find_element(By.CSS_SELECTOR, "[aria-label='Warenkorb']")
                    cart_text = cart_sidebar.text
                    print(f"Cart sidebar text: {cart_text[:200]}")
                    
                    if "Noch nichts passendes gefunden" in cart_text or "nichts" in cart_text.lower():
                        print("⚠️  Cart sidebar shows empty state")
                    else:
                        print("✅ Cart sidebar has content (product may be added)")
                except Exception as e:
                    print(f"Could not check cart sidebar: {e}")
                
                # Try clicking the cart icon in header to see count
                print("Checking cart icon in header...")
                try:
                    cart_button = driver.find_element(By.ID, "toggleShoppingCartButton")
                    cart_aria = cart_button.get_attribute("aria-label")
                    print(f"Cart button aria-label: {cart_aria}")
                    
                    if "Keine Produkte" in cart_aria:
                        print("⚠️ Cart icon shows: No products in cart")
                    else:
                        print("✅ Cart icon may show items")
                except Exception as e:
                    print(f"Could not check cart icon: {e}")
                

                
                break
                
            except (TimeoutException, NoSuchElementException) as e:
                print(f"Selector failed: {e}")
                continue
        
        if not button_found:
            # Try to find any button containing cart-related text
            print("Primary selectors failed, scanning all buttons...")
            try:
                buttons = driver.find_elements(By.TAG_NAME, "button")
                print(f"Found {len(buttons)} buttons on page")
                for i, button in enumerate(buttons):
                    try:
                        text = button.text.lower() if button.text else ""
                        aria_label = button.get_attribute("aria-label") or ""
                        aria_label_lower = aria_label.lower()
                        class_name = button.get_attribute("class") or ""
                        
                        print(f"Button {i}: text='{button.text[:50]}', aria-label='{aria_label[:50]}', class='{class_name[:50]}'")
                        
                        if any(word in text for word in ["warenkorb", "cart", "kaufen", "bestellen", "in den warenkorb"]):
                            print(f"Found cart button by text: {button.text}")
                            driver.execute_script("arguments[0].scrollIntoView(true);", button)
                            time.sleep(0.5)
                            button.click()
                            button_found = True
                            break
                        elif any(word in aria_label_lower for word in ["warenkorb", "cart", "kaufen"]):
                            print(f"Found cart button by aria-label: {aria_label}")
                            driver.execute_script("arguments[0].scrollIntoView(true);", button)
                            time.sleep(0.5)
                            button.click()
                            button_found = True
                            break
                    except Exception as e:
                        continue
                        
            except Exception as e:
                print(f"Button search failed: {e}")
        
        if not button_found:
            # Save screenshot for debugging
            screenshot_path = "debug_no_cart_button.png"
            driver.save_screenshot(screenshot_path)
            print(f"Screenshot saved to: {screenshot_path}")
            
            # Also save page source
            with open("debug_page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Page source saved to: debug_page_source.html")
            
            return {
                "success": False,
                "message": f"Warenkorb-Button nicht gefunden. Screenshot: {screenshot_path}",
                "cart_url": None
            }
        
        # Wait for cart update
        time.sleep(2)
        
        # Get cart URL
        cart_url = "https://www.digitec.ch/cart"
        
        return {
            "success": True,
            "message": "Produkt wurde zum Warenkorb hinzugefügt",
            "cart_url": cart_url
        }
        
    except Exception as e:
        print(f"Error in add_product_to_cart: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Try to save debug info even on error
        try:
            if driver:
                screenshot_path = "debug_error_screenshot.png"
                driver.save_screenshot(screenshot_path)
                print(f"Error screenshot saved to: {screenshot_path}")
                
                with open("debug_error_page_source.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print("Error page source saved to: debug_error_page_source.html")
        except:
            pass
            
        return {
            "success": False,
            "message": f"Fehler: {str(e)}",
            "cart_url": None
        }
        
    finally:
        if driver:
            try:
                print("Closing browser...")
                driver.quit()
                print("Browser closed successfully")
            except Exception as e:
                print(f"Error closing driver: {e}")


def add_multiple_products_to_cart(product_urls: list, email: str = None, password: str = None) -> dict:
    """
    Add multiple products to the cart in one session
    
    Args:
        product_urls: List of product URLs to add
        email: Digitec account email (optional)
        password: Digitec account password (optional)
    
    Returns:
        dict: {"success": bool, "added": int, "failed": int, "cart_url": str}
    """
    driver = None
    added = 0
    failed = 0
    
    try:
        driver = make_driver(headless=True)
        
        # Login once for all products
        if email and password:
            login_success = login_to_digitec(driver, email, password)
            if not login_success:
                return {
                    "success": False,
                    "added": 0,
                    "failed": len(product_urls),
                    "message": "Login fehlgeschlagen",
                    "cart_url": None
                }
        
        # Process each product
        for url in product_urls:
            try:
                driver.get(url)
                wait = WebDriverWait(driver, 10)
                
                # Wait for page to load
                time.sleep(2)
                
                # Try to find and click add to cart button using the ID
                try:
                    add_button = wait.until(EC.element_to_be_clickable((By.ID, "addToCartButton")))
                    driver.execute_script("arguments[0].scrollIntoView(true);", add_button)
                    time.sleep(0.3)
                    
                    # Use JavaScript click (more reliable)
                    driver.execute_script("arguments[0].click();", add_button)
                    added += 1
                    time.sleep(1.5)  # Wait for cart to update
                    
                except Exception as e:
                    print(f"Failed to add {url}: {e}")
                    failed += 1
                    
            except Exception as e:
                print(f"Error processing {url}: {e}")
                failed += 1
        
        return {
            "success": added > 0,
            "added": added,
            "failed": failed,
            "message": f"{added} Produkt(e) hinzugefügt, {failed} fehlgeschlagen",
            "cart_url": "https://www.galaxus.ch/de/checkout/cart"
        }
        
    except Exception as e:
        print(f"Error in add_multiple_products_to_cart: {str(e)}")
        return {
            "success": False,
            "added": added,
            "failed": failed,
            "message": f"Fehler: {str(e)}",
            "cart_url": None
        }
        
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

