#!/usr/bin/env python3
"""
Infrastructure verification script for LOHI-TRADE.

This script verifies that all foundational infrastructure components are working:
1. Redis container is running and accessible
2. Database connections (SQLite and DuckDB) are working
3. Configuration loads correctly
4. Logging system writes to files

Usage:
    python scripts/verify_infrastructure.py
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def verify_redis():
    """Verify Redis container is running and accessible."""
    print("\n=== Verifying Redis ===")
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        r.ping()
        print("✓ Redis connection successful")
        
        # Test basic operations
        r.set('test_key', 'test_value', ex=10)
        value = r.get('test_key')
        if value == 'test_value':
            print("✓ Redis read/write operations working")
        r.delete('test_key')
        
        return True
    except Exception as e:
        print(f"✗ Redis verification failed: {e}")
        return False


def verify_databases():
    """Verify SQLite and DuckDB connections."""
    print("\n=== Verifying Databases ===")
    try:
        from src.state.database import DatabaseConnectionManager
        
        db_manager = DatabaseConnectionManager()
        
        # Test SQLite
        if db_manager.health_check_sqlite():
            conn = db_manager.connect_sqlite()
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM sqlite_master WHERE type="table" ORDER BY name')
            tables = [row[0] for row in cursor.fetchall()]
            print(f"✓ SQLite connection successful with {len(tables)} tables")
            print(f"  Tables: {', '.join(tables)}")
        else:
            print("✗ SQLite health check failed")
            return False
        
        # Test DuckDB
        if db_manager.health_check_duckdb():
            print("✓ DuckDB connection successful")
        else:
            print("⚠ DuckDB not available (optional)")
        
        db_manager.close()
        return True
        
    except Exception as e:
        print(f"✗ Database verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_configuration():
    """Verify configuration loads correctly."""
    print("\n=== Verifying Configuration ===")
    
    # Set mock environment variables for testing
    env_vars = {
        'SHOONYA_API_KEY': 'test_key',
        'SHOONYA_CLIENT_ID': 'test_client',
        'SHOONYA_PASSWORD': 'test_pass',
        'ANGELONE_API_KEY': 'test_key',
        'ANGELONE_CLIENT_ID': 'test_client',
        'ANGELONE_PASSWORD': 'test_pass',
        'TELEGRAM_BOT_TOKEN': 'test_token',
        'TELEGRAM_CHAT_ID': 'test_chat',
    }
    
    for key, value in env_vars.items():
        if key not in os.environ:
            os.environ[key] = value
    
    try:
        from src.utils.config import load_config
        
        config = load_config()
        print("✓ Configuration loaded successfully")
        print(f"  - Capital: ₹{config.capital.total:,}")
        print(f"  - Risk per trade: {config.capital.risk_per_trade_pct}%")
        print(f"  - Max positions: {config.risk_limits.max_open_positions}")
        print(f"  - Primary broker: {config.broker.primary}")
        print(f"  - Redis: {config.redis.host}:{config.redis.port}")
        print(f"  - Symbols: {len(config.symbols)} configured")
        
        strategies_enabled = sum(1 for s in [
            config.strategies.mean_reversion.enabled,
            config.strategies.trend_following.enabled,
            config.strategies.opening_range_breakout.enabled
        ] if s)
        print(f"  - Strategies enabled: {strategies_enabled}/3")
        
        return True
        
    except Exception as e:
        print(f"✗ Configuration verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_logging():
    """Verify logging system writes to files."""
    print("\n=== Verifying Logging ===")
    try:
        from src.utils.logger import get_logger
        
        # Get logger and write test messages
        logger = get_logger('infrastructure_verification')
        logger.info('Infrastructure checkpoint: Testing logging system')
        logger.warning('Test warning message')
        
        # Check if log file was created
        log_dir = Path('data/logs')
        log_files = list(log_dir.glob('*.log'))
        
        if log_files:
            print(f"✓ Logging working - {len(log_files)} log file(s) found")
            for log_file in log_files:
                size = log_file.stat().st_size
                print(f"  - {log_file.name} ({size:,} bytes)")
            return True
        else:
            print(f"✗ No log files found in {log_dir}")
            return False
            
    except Exception as e:
        print(f"✗ Logging verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all infrastructure verification checks."""
    print("=" * 60)
    print("LOHI-TRADE Infrastructure Verification")
    print("=" * 60)
    
    results = {
        'Redis': verify_redis(),
        'Databases': verify_databases(),
        'Configuration': verify_configuration(),
        'Logging': verify_logging(),
    }
    
    print("\n" + "=" * 60)
    print("Verification Summary")
    print("=" * 60)
    
    for component, status in results.items():
        status_icon = "✓" if status else "✗"
        print(f"{status_icon} {component}: {'PASS' if status else 'FAIL'}")
    
    all_passed = all(results.values())
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All infrastructure components verified successfully!")
        print("=" * 60)
        return 0
    else:
        print("✗ Some infrastructure components failed verification")
        print("=" * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
