import requests
import time
import sqlite3
import logging
import json
import os
from datetime import datetime, timedelta
import threading
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = 15  # seconds
PERFORMANCE_INTERVALS = [1, 6, 24]  # hours
DB_PATH = "dexscanner_monitor.db"
LOG_FILE = "dexscanner_monitor.log"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("DexscannerMonitor")

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize database with required tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table for tracked tokens
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id TEXT PRIMARY KEY,
            pair_name TEXT,
            deployer TEXT,
            owner_renounced INTEGER,
            launch_time TIMESTAMP,
            mint_enabled INTEGER,
            liq_burned REAL,
            chain TEXT,
            initial_mc REAL,
            initial_liq REAL,
            website TEXT,
            source TEXT,
            detected_at TIMESTAMP,
            is_safe INTEGER DEFAULT 0
        )
        ''')
        
        # Table for token price performance
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS token_performance (
            id TEXT,
            timestamp TIMESTAMP,
            price REAL,
            market_cap REAL,
            volume_24h REAL,
            holders INTEGER,
            PRIMARY KEY (id, timestamp),
            FOREIGN KEY (id) REFERENCES tokens(id)
        )
        ''')
        
        # Table for security checks
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS security_checks (
            id TEXT PRIMARY KEY,
            has_honey_pot INTEGER,
            has_mint_function INTEGER,
            has_proxy INTEGER,
            has_suspicious_holders INTEGER,
            check_time TIMESTAMP,
            FOREIGN KEY (id) REFERENCES tokens(id)
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    
    def token_exists(self, token_id):
        """Check if token already exists in database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tokens WHERE id = ?", (token_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    
    def add_token(self, token_data):
        """Add new token to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO tokens (
            id, pair_name, deployer, owner_renounced, launch_time, 
            mint_enabled, liq_burned, chain, initial_mc, initial_liq, 
            website, source, detected_at, is_safe
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            token_data["id"],
            token_data["pair_name"],
            token_data["deployer"],
            1 if token_data["owner_renounced"] else 0,
            token_data["launch_time"],
            0 if token_data["mint_enabled"] == "No ✅" else 1,
            token_data["liq_burned"],
            token_data["chain"],
            token_data["initial_mc"],
            token_data["initial_liq"],
            token_data["website"],
            token_data["source"],
            datetime.now().isoformat(),
            0
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"Added new token to database: {token_data['pair_name']}")
    
    def update_token_performance(self, token_id, performance_data):
        """Update token performance metrics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO token_performance (
            id, timestamp, price, market_cap, volume_24h, holders
        ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            token_id,
            datetime.now().isoformat(),
            performance_data["price"],
            performance_data["market_cap"],
            performance_data["volume_24h"],
            performance_data["holders"]
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"Updated performance data for token: {token_id}")
    
    def update_security_check(self, token_id, security_data):
        """Update security check results"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT OR REPLACE INTO security_checks (
            id, has_honey_pot, has_mint_function, has_proxy, 
            has_suspicious_holders, check_time
        ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            token_id,
            security_data["has_honey_pot"],
            security_data["has_mint_function"],
            security_data["has_proxy"],
            security_data["has_suspicious_holders"],
            datetime.now().isoformat()
        ))
        
        # Update token safety status
        is_safe = not any([
            security_data["has_honey_pot"],
            security_data["has_mint_function"],
            security_data["has_proxy"],
            security_data["has_suspicious_holders"]
        ])
        
        cursor.execute('''
        UPDATE tokens SET is_safe = ? WHERE id = ?
        ''', (1 if is_safe else 0, token_id))
        
        conn.commit()
        conn.close()
        logger.info(f"Updated security checks for token: {token_id}")
    
    def get_token_performance_history(self, token_id, hours=24):
        """Get token performance history for specified hours"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        time_threshold = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        cursor.execute('''
        SELECT timestamp, price, market_cap, volume_24h, holders
        FROM token_performance
        WHERE id = ? AND timestamp >= ?
        ORDER BY timestamp ASC
        ''', (token_id, time_threshold))
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return None
        
        performance_data = []
        for row in results:
            performance_data.append({
                "timestamp": row[0],
                "price": row[1],
                "market_cap": row[2],
                "volume_24h": row[3],
                "holders": row[4]
            })
        
        return performance_data
    
    def get_tokens_for_performance_check(self):
        """Get tokens that need performance monitoring"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get tokens detected in the past week
        time_threshold = (datetime.now() - timedelta(days=7)).isoformat()
        
        cursor.execute('''
        SELECT id, pair_name, detected_at
        FROM tokens
        WHERE detected_at >= ?
        ''', (time_threshold,))
        
        results = cursor.fetchall()
        conn.close()
        
        tokens = []
        for row in results:
            tokens.append({
                "id": row[0],
                "pair_name": row[1],
                "detected_at": row[2]
            })
        
        return tokens


class DexscannerAPI:
    def __init__(self):
        self.base_url = "https://api.dexscanner.io"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json"
        }
    
    def get_new_listings(self, chain="sol", max_retries=5, timeout=20):
        """Get new listings from Dexscanner API with retry logic"""
        retries = 0
        while retries < max_retries:
            try:
                url = f"{self.base_url}/v1/{chain}/dex/pairs/new"
                logger.info(f"Fetching new listings from {url}")
                response = requests.get(url, headers=self.headers, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.Timeout as e:
                retries += 1
                wait_time = 3 + retries * 3  # Exponential backoff
                logger.warning(f"Timeout fetching new listings (attempt {retries}/{max_retries}). Retrying in {wait_time} seconds: {e}")
                time.sleep(wait_time)
            except requests.RequestException as e:
                logger.error(f"Error fetching new listings: {e}")
                return None
        
        logger.error(f"Failed to fetch new listings after {max_retries} attempts")
        return None
    
    def get_token_details(self, token_id, chain="sol", max_retries=3, timeout=10):
        """Get detailed information about a token with retry logic"""
        retries = 0
        while retries < max_retries:
            try:
                url = f"{self.base_url}/v1/{chain}/dex/pairs/{token_id}"
                response = requests.get(url, headers=self.headers, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.Timeout as e:
                retries += 1
                wait_time = 2 ** retries  # Exponential backoff
                logger.warning(f"Timeout fetching token details for {token_id} (attempt {retries}/{max_retries}). Retrying in {wait_time} seconds: {e}")
                time.sleep(wait_time)
            except requests.RequestException as e:
                logger.error(f"Error fetching token details for {token_id}: {e}")
                return None
        
        logger.error(f"Failed to fetch token details for {token_id} after {max_retries} attempts")
        return None

class SecurityValidator:
    @staticmethod
    def validate_token(token_details):
        """Validate token for potential security issues"""
        security_data = {
            "has_honey_pot": False,
            "has_mint_function": False,
            "has_proxy": False,
            "has_suspicious_holders": False
        }
        
        # Check for mint function (basic check based on details)
        if "mint" in str(token_details).lower() and "enabled" in str(token_details).lower():
            security_data["has_mint_function"] = True
        
        # Check for suspicious holder concentration (if top 10 holders have more than 80%)
        if "holders" in token_details and "top10" in token_details["holders"]:
            top10_percentage = float(token_details["holders"]["top10"].replace("%", ""))
            if top10_percentage > 80:
                security_data["has_suspicious_holders"] = True
        
        # Additional security checks can be implemented here
        # These would typically require contract analysis which might need integration
        # with specialized APIs or services
        
        return security_data


class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, message, parse_mode="Markdown"):
        """Send message to Telegram chat"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": parse_mode
            }
            response = requests.post(url, json=payload)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False
    
    def format_token_message(self, token_data):
        """Format token data into readable message for Telegram"""
        message = (
            f"📌 Pair: {token_data['pair_name']}\n"
            f"👨‍💻 Deployer: {token_data['deployer']}\n"
            f"👤 Owner: {'RENOUNCED' if token_data['owner_renounced'] else 'NOT RENOUNCED'}\n"
            f"🔸 Chain: {token_data['chain']} | ⚖️ Age: {token_data['age']}\n"
            f"🌿 Mint: {token_data['mint_enabled']} | Liq: 🔥 ({token_data['liq_burned']}%)\n"
            f"💰 MC: ${token_data['market_cap']} | Liq: ${token_data['liquidity']} ({token_data['liq_percentage']}%)\n"
            f"📈 24h: {token_data['price_change_24h']}% | V: ${token_data['volume_24h']} | B:{token_data['buys']} S:{token_data['sells']}\n"
            f"💲 Price: ${token_data['price']}\n"
            f"💵 Launch MC: ${token_data['launch_mc']} ({token_data['launch_mc_multiplier']}x)\n"
            f"👆 ATH: ${token_data['ath']} ({token_data['ath_multiplier']}x)\n"
            f"🔗 Website ({token_data['source_link']})\n"
            f"📊 TS: {token_data['transaction_count']}\n"
            f"👩‍👧‍👦 Holders: {token_data['holders_count']} | Top10: {token_data['top10_percentage']}%\n"
            f"💸 Airdrops: {token_data['airdrops']} for a total of {token_data['airdrops_percentage']}%\n"
            f"🥡 Block 0 Snipes: {token_data['block0_snipes_percentage']}% | {token_data['block0_snipes_amount']} SOL\n"
            f"👶🏽 Fresh Wallets: {token_data['fresh_wallets']} | {token_data['fresh_wallets_percentage']}% Time\n"
            f"💵 TEAM WALLETS {token_data['team_wallets_percentage']}% | {token_data['team_wallets_amount']} SOL\n"
            f"Deployer {token_data['deployer_amount']} SOL | {token_data['deployer_percentage']}% Time"
        )
        
        # Add security warnings if applicable
        if hasattr(token_data, 'security_warnings') and token_data['security_warnings']:
            message += "\n\n⚠️ SECURITY WARNINGS ⚠️\n"
            for warning in token_data['security_warnings']:
                message += f"- {warning}\n"
        
        return message
    
    def format_performance_update(self, token_data, performance_data):
        """Format performance update for a token"""
        # Calculate price changes
        first_price = performance_data[0]["price"] if performance_data else 0
        current_price = performance_data[-1]["price"] if performance_data else 0
        price_change = ((current_price - first_price) / first_price * 100) if first_price > 0 else 0
        
        message = (
            f"📊 PERFORMANCE UPDATE 📊\n"
            f"📌 Pair: {token_data['pair_name']}\n"
            f"💲 Current Price: ${current_price:.8f}\n"
            f"📈 Price Change: {price_change:.2f}%\n"
            f"💰 Current MC: ${performance_data[-1]['market_cap']}\n"
            f"👥 Holders: {performance_data[-1]['holders']}\n"
            f"🔄 24h Volume: ${performance_data[-1]['volume_24h']}\n"
            f"⏰ Monitored since: {token_data['detected_at']}\n"
        )
        
        return message


class DexscannerMonitor:
    def __init__(self):
        self.db = Database(DB_PATH)
        self.api = DexscannerAPI()
        self.validator = SecurityValidator()
        self.notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.last_check_time = datetime.now()
        self.processed_tokens = set()
    
    def parse_token_details(self, token_raw, details_raw=None):
        """Parse token details from API response"""
        if not details_raw:
            details_raw = {}
        
        # Check if this is from pump.fun or pump.swap
        source = None
        if "name" in token_raw:
            name_lower = token_raw["name"].lower()
            if "pump.fun" in name_lower:
                source = "pump.fun"
            elif "pump.swap" in name_lower:
                source = "pump.swap"
        
        # If not from our target sources, return None
        if not source:
            return None
        
        # Basic details
        token_data = {
            "id": token_raw.get("id", ""),
            "pair_name": token_raw.get("name", "Unknown"),
            "deployer": details_raw.get("deployer", "Unknown"),
            "owner_renounced": details_raw.get("ownerRenounced", False),
            "chain": "SOL",
            "age": self._format_age(token_raw.get("createdAt")),
            "launch_time": token_raw.get("createdAt"),
            "mint_enabled": "No ✅" if not details_raw.get("mintEnabled", True) else "Yes ⚠️",
            "liq_burned": details_raw.get("liquidityBurned", 0),
            "market_cap": self._format_number(token_raw.get("marketCap", 0)),
            "liquidity": self._format_number(token_raw.get("liquidity", 0)),
            "liq_percentage": self._calculate_percentage(token_raw.get("liquidity", 0), token_raw.get("marketCap", 0)),
            "price": self._format_number(token_raw.get("price", 0), 8),
            "price_change_24h": token_raw.get("priceChange24h", 0),
            "volume_24h": self._format_number(token_raw.get("volume24h", 0)),
            "buys": details_raw.get("buys24h", 0),
            "sells": details_raw.get("sells24h", 0),
            "launch_mc": self._format_number(details_raw.get("launchMarketCap", 0)),
            "launch_mc_multiplier": self._calculate_multiplier(token_raw.get("marketCap", 0), details_raw.get("launchMarketCap", 0)),
            "ath": self._format_number(details_raw.get("athMarketCap", 0)),
            "ath_multiplier": self._calculate_multiplier(details_raw.get("athMarketCap", 0), token_raw.get("marketCap", 0)),
            "source": source,
            "source_link": f"https://{source}",
            "transaction_count": details_raw.get("transactionCount", 0),
            "holders_count": details_raw.get("holdersCount", 0),
            "top10_percentage": details_raw.get("top10HoldersPercentage", 0),
            "airdrops": details_raw.get("airdropsCount", 0),
            "airdrops_percentage": details_raw.get("airdropsPercentage", 0),
            "block0_snipes_percentage": details_raw.get("block0SnipesPercentage", 0),
            "block0_snipes_amount": details_raw.get("block0SnipesAmount", 0),
            "fresh_wallets": details_raw.get("freshWalletsCount", 0),
            "fresh_wallets_percentage": details_raw.get("freshWalletsPercentage", 0),
            "team_wallets_percentage": details_raw.get("teamWalletsPercentage", 0),
            "team_wallets_amount": details_raw.get("teamWalletsAmount", 0),
            "deployer_amount": details_raw.get("deployerAmount", 0),
            "deployer_percentage": details_raw.get("deployerPercentage", 0),
            "website": details_raw.get("website", f"https://{source}"),
            "initial_mc": token_raw.get("marketCap", 0),
            "initial_liq": token_raw.get("liquidity", 0)
        }
        
        # Extract performance data for DB
        performance_data = {
            "price": token_raw.get("price", 0),
            "market_cap": token_raw.get("marketCap", 0),
            "volume_24h": token_raw.get("volume24h", 0),
            "holders": details_raw.get("holdersCount", 0)
        }
        
        # Run security validation
        security_data = self.validator.validate_token(details_raw)
        
        # Add security warnings if any
        if any(security_data.values()):
            token_data["security_warnings"] = []
            if security_data["has_honey_pot"]:
                token_data["security_warnings"].append("Potential honeypot detected")
            if security_data["has_mint_function"]:
                token_data["security_warnings"].append("Token has mint function enabled")
            if security_data["has_proxy"]:
                token_data["security_warnings"].append("Contract may have proxy capabilities")
            if security_data["has_suspicious_holders"]:
                token_data["security_warnings"].append("Suspicious holder concentration detected")
        
        return token_data, performance_data, security_data
    
    def check_new_listings(self):
        """Check for new listings on Dexscanner"""
        logger.info("Checking for new listings...")
        
        # Get new listings
        listings = self.api.get_new_listings()
        if not listings or "data" not in listings:
            logger.warning("No data received from API or invalid response")
            return
        
        # Process each listing
        for token in listings.get("data", []):
            token_id = token.get("id")
            
            # Skip if already processed or in DB
            if token_id in self.processed_tokens or self.db.token_exists(token_id):
                continue
            
            # Get token details
            token_details = self.api.get_token_details(token_id)
            if not token_details or "data" not in token_details:
                continue
            
            # Parse token data
            parsed_data = self.parse_token_details(token, token_details.get("data"))
            if not parsed_data:
                continue
            
            token_data, performance_data, security_data = parsed_data
            
            # Add to processed tokens
            self.processed_tokens.add(token_id)
            
            # Save to database
            self.db.add_token(token_data)
            self.db.update_token_performance(token_id, performance_data)
            self.db.update_security_check(token_id, security_data)
            
            # Send notification
            message = self.notifier.format_token_message(token_data)
            self.notifier.send_message(message)
            
            logger.info(f"New token detected and notified: {token_data['pair_name']}")
    
    def monitor_performance(self):
        """Monitor performance of previously detected tokens"""
        tokens = self.db.get_tokens_for_performance_check()
        now = datetime.now()
        
        for token in tokens:
            token_id = token["id"]
            detected_time = datetime.fromisoformat(token["detected_at"])
            hours_since_detection = (now - detected_time).total_seconds() / 3600
            
            # Get token details for update
            token_details = self.api.get_token_details(token_id)
            if not token_details or "data" not in token_details:
                continue
            
            # Parse token data for performance update
            parsed_data = self.parse_token_details(
                {"id": token_id, "name": token["pair_name"]}, 
                token_details.get("data")
            )
            
            if not parsed_data:
                continue
            
            _, performance_data, _ = parsed_data
            
            # Update performance in DB
            self.db.update_token_performance(token_id, performance_data)
            
            # Check if we should send performance update
            for interval in PERFORMANCE_INTERVALS:
                # If the time since detection matches an interval (+/- 10 minutes)
                if abs(hours_since_detection - interval) < 0.17:  # ~10 minutes
                    history = self.db.get_token_performance_history(token_id, hours=interval)
                    if history and len(history) >= 2:
                        message = self.notifier.format_performance_update(token, history)
                        self.notifier.send_message(message)
                        logger.info(f"Sent {interval}h performance update for {token['pair_name']}")
                    break
    
    def run(self):
        """Main monitoring loop"""
        logger.info("Starting Dexscanner monitor...")
        
        # Create and start performance monitoring thread
        performance_thread = threading.Thread(target=self._performance_monitor_loop)
        performance_thread.daemon = True
        performance_thread.start()
        
        # Main loop for checking new listings
        while True:
            try:
                self.check_new_listings()
                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(CHECK_INTERVAL * 2)  # Wait longer on error
    
    def _performance_monitor_loop(self):
        """Separate loop for performance monitoring"""
        while True:
            try:
                self.monitor_performance()
                time.sleep(60 * 15)  # Check every 15 minutes
            except Exception as e:
                logger.error(f"Error in performance monitoring loop: {e}")
                time.sleep(60 * 30)  # Wait longer on error
    
    def _format_age(self, timestamp):
        """Format timestamp into readable age"""
        if not timestamp:
            return "Unknown"
        
        try:
            created_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            now = datetime.now().astimezone()
            delta = now - created_time
            
            if delta.days > 0:
                return f"{delta.days}d {delta.seconds // 3600}h"
            elif delta.seconds // 3600 > 0:
                return f"{delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
            else:
                return f"{(delta.seconds % 3600) // 60}m"
        except Exception:
            return "Unknown"
    
    def _format_number(self, number, decimals=1):
        """Format number with K, M, B suffixes"""
        if number is None:
            return "0"
        
        try:
            number = float(number)
            if number < 1000:
                return f"{number:.{decimals}f}"
            elif number < 1000000:
                return f"{number/1000:.{decimals}f}K"
            elif number < 1000000000:
                return f"{number/1000000:.{decimals}f}M"
            else:
                return f"{number/1000000000:.{decimals}f}B"
        except:
            return "0"
    
    def _calculate_percentage(self, part, whole):
        """Calculate percentage"""
        try:
            if whole == 0:
                return 0
            return round((part / whole) * 100)
        except:
            return 0
    
    def _calculate_multiplier(self, current, reference):
        """Calculate multiplier (e.g., ATH multiplier)"""
        try:
            if reference == 0:
                return "1x"
            multiplier = current / reference
            return f"{multiplier:.1f}x"
        except:
            return "1x"


# Entry point
if __name__ == "__main__":
    monitor = DexscannerMonitor()
    monitor.check_new_listings()
    # Check if environment variables are set
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment variables")
        print("Please create a .env file with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        exit(1)
    
    # Start the monitor
    monitor = DexscannerMonitor()
    monitor.run()
