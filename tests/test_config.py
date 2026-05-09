"""
Unit tests for configuration management.

Tests cover:
- Missing required fields
- Invalid data types
- Environment variable overrides
- Time format validation
- Percentage validation
"""

import os
import pytest
import tempfile
from pathlib import Path

from src.utils.config import (
    load_config,
    substitute_env_vars,
    validate_time_format,
    validate_required_fields,
    validate_positive_number,
    validate_percentage,
    ConfigurationError,
    Config,
)


class TestEnvironmentVariableSubstitution:
    """Test environment variable substitution in configuration."""
    
    def test_substitute_simple_env_var(self):
        """Test substitution of a single environment variable."""
        os.environ['TEST_VAR'] = 'test_value'
        result = substitute_env_vars('${TEST_VAR}')
        assert result == 'test_value'
        del os.environ['TEST_VAR']
    
    def test_substitute_multiple_env_vars(self):
        """Test substitution of multiple environment variables in one string."""
        os.environ['VAR1'] = 'value1'
        os.environ['VAR2'] = 'value2'
        result = substitute_env_vars('${VAR1}_${VAR2}')
        assert result == 'value1_value2'
        del os.environ['VAR1']
        del os.environ['VAR2']
    
    def test_substitute_env_var_in_dict(self):
        """Test substitution in nested dictionary."""
        os.environ['TEST_KEY'] = 'test_value'
        data = {'key1': '${TEST_KEY}', 'key2': {'nested': '${TEST_KEY}'}}
        result = substitute_env_vars(data)
        assert result['key1'] == 'test_value'
        assert result['key2']['nested'] == 'test_value'
        del os.environ['TEST_KEY']
    
    def test_substitute_env_var_in_list(self):
        """Test substitution in list."""
        os.environ['TEST_ITEM'] = 'item_value'
        data = ['${TEST_ITEM}', 'static_value']
        result = substitute_env_vars(data)
        assert result[0] == 'item_value'
        assert result[1] == 'static_value'
        del os.environ['TEST_ITEM']
    
    def test_missing_env_var_raises_error(self):
        """Test that missing environment variable raises ConfigurationError."""
        with pytest.raises(ConfigurationError) as exc_info:
            substitute_env_vars('${NONEXISTENT_VAR}')
        assert 'NONEXISTENT_VAR' in str(exc_info.value)
        assert 'not set' in str(exc_info.value)
    
    def test_no_substitution_for_non_string(self):
        """Test that non-string values are returned unchanged."""
        assert substitute_env_vars(123) == 123
        assert substitute_env_vars(45.67) == 45.67
        assert substitute_env_vars(True) is True


class TestValidationFunctions:
    """Test validation helper functions."""
    
    def test_validate_time_format_valid(self):
        """Test validation of valid time formats."""
        validate_time_format('09:15', 'test_field')
        validate_time_format('15:30', 'test_field')
        validate_time_format('00:00', 'test_field')
        validate_time_format('23:59', 'test_field')
    
    def test_validate_time_format_invalid(self):
        """Test validation rejects invalid time formats."""
        with pytest.raises(ConfigurationError) as exc_info:
            validate_time_format('25:00', 'test_field')
        assert 'Invalid time format' in str(exc_info.value)
        
        with pytest.raises(ConfigurationError):
            validate_time_format('9:15', 'test_field')  # Missing leading zero
        
        with pytest.raises(ConfigurationError):
            validate_time_format('09:60', 'test_field')  # Invalid minutes
    
    def test_validate_required_fields_all_present(self):
        """Test validation passes when all required fields are present."""
        data = {'field1': 'value1', 'field2': 'value2'}
        validate_required_fields(data, ['field1', 'field2'], 'test_section')
    
    def test_validate_required_fields_missing(self):
        """Test validation fails when required fields are missing."""
        data = {'field1': 'value1'}
        with pytest.raises(ConfigurationError) as exc_info:
            validate_required_fields(data, ['field1', 'field2', 'field3'], 'test_section')
        assert 'Missing required fields' in str(exc_info.value)
        assert 'field2' in str(exc_info.value)
        assert 'field3' in str(exc_info.value)
    
    def test_validate_positive_number_valid(self):
        """Test validation of positive numbers."""
        validate_positive_number(100, 'test_field')
        validate_positive_number(0.5, 'test_field')
        validate_positive_number(1, 'test_field')
    
    def test_validate_positive_number_invalid(self):
        """Test validation rejects non-positive numbers."""
        with pytest.raises(ConfigurationError) as exc_info:
            validate_positive_number(0, 'test_field')
        assert 'must be a positive number' in str(exc_info.value)
        
        with pytest.raises(ConfigurationError):
            validate_positive_number(-10, 'test_field')
        
        with pytest.raises(ConfigurationError):
            validate_positive_number('not_a_number', 'test_field')
    
    def test_validate_percentage_valid(self):
        """Test validation of valid percentages."""
        validate_percentage(0, 'test_field')
        validate_percentage(50, 'test_field')
        validate_percentage(100, 'test_field')
        validate_percentage(25.5, 'test_field')
    
    def test_validate_percentage_invalid(self):
        """Test validation rejects invalid percentages."""
        with pytest.raises(ConfigurationError) as exc_info:
            validate_percentage(-1, 'test_field')
        assert 'must be a percentage between 0 and 100' in str(exc_info.value)
        
        with pytest.raises(ConfigurationError):
            validate_percentage(101, 'test_field')
        
        with pytest.raises(ConfigurationError):
            validate_percentage('not_a_number', 'test_field')


class TestConfigurationLoading:
    """Test configuration loading and validation."""
    
    def create_temp_config(self, config_content: str) -> str:
        """Helper to create a temporary config file."""
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        temp_file.write(config_content)
        temp_file.close()
        return temp_file.name
    
    def test_load_valid_config(self):
        """Test loading a valid configuration file."""
        # Set required environment variables
        os.environ['SHOONYA_API_KEY'] = 'test_key'
        os.environ['SHOONYA_CLIENT_ID'] = 'test_client'
        os.environ['SHOONYA_PASSWORD'] = 'test_pass'
        os.environ['ANGELONE_API_KEY'] = 'test_key'
        os.environ['ANGELONE_CLIENT_ID'] = 'test_client'
        os.environ['ANGELONE_PASSWORD'] = 'test_pass'
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token'
        os.environ['TELEGRAM_CHAT_ID'] = 'test_chat'
        
        config_content = """
capital:
  total: 200000
  risk_per_trade_pct: 1.0
  max_position_size_pct: 20.0
  max_daily_loss_pct: 2.0

risk_limits:
  max_open_positions: 5
  max_orders_per_day: 20
  cooldown_after_loss_minutes: 5
  volatility_guard_threshold_pct: 2.0
  volatility_guard_window_minutes: 10

trading_hours:
  market_open: "09:15"
  trading_start: "09:30"
  trading_end: "15:10"
  square_off_time: "15:15"
  market_close: "15:30"

broker:
  primary: "shoonya"
  backup: "angelone"
  shoonya:
    api_key: "${SHOONYA_API_KEY}"
    client_id: "${SHOONYA_CLIENT_ID}"
    password: "${SHOONYA_PASSWORD}"
  angelone:
    api_key: "${ANGELONE_API_KEY}"
    client_id: "${ANGELONE_CLIENT_ID}"
    password: "${ANGELONE_PASSWORD}"

strategies:
  mean_reversion:
    enabled: true
    rsi_oversold: 30
    rsi_overbought: 65
    volume_multiplier: 1.5
    stop_loss_atr_multiplier: 1.5
  trend_following:
    enabled: true
    ema_fast: 9
    ema_slow: 21
    stop_loss_atr_multiplier: 2.0
    target_atr_multiplier: 3.0
  opening_range_breakout:
    enabled: true
    range_start: "09:15"
    range_end: "09:30"
    trade_window_start: "09:30"
    trade_window_end: "10:30"
    volume_multiplier: 2.0
    target_multiplier: 1.5

sentiment:
  bias_bullish_threshold: 0.2
  bias_bearish_threshold: -0.2
  time_decay_half_life_hours: 4.0
  lookback_hours: 24
  recalculation_interval_minutes: 5

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
  rate_limit_messages_per_hour: 20

redis:
  host: "localhost"
  port: 6379
  db: 0

database:
  sqlite_path: "data/lohi_trade.db"
  duckdb_path: "data/historical.duckdb"
  backup_path: "data/backups"
  backup_time: "16:00"

logging:
  level: "INFO"
  log_dir: "data/logs"
  max_file_size_mb: 100
  backup_count: 10

paper_trading:
  enabled: false
  simulated_fill_delay_ms: [100, 500]
  simulated_slippage_pct: 0.05

symbols:
  - "RELIANCE"
  - "TCS"
"""
        
        temp_config_path = self.create_temp_config(config_content)
        
        try:
            config = load_config(temp_config_path)
            
            # Verify configuration was loaded correctly
            assert isinstance(config, Config)
            assert config.capital.total == 200000
            assert config.capital.risk_per_trade_pct == 1.0
            assert config.risk_limits.max_open_positions == 5
            assert config.trading_hours.market_open == "09:15"
            assert config.broker.primary == "shoonya"
            assert config.broker.shoonya.api_key == "test_key"
            assert config.strategies.mean_reversion.enabled is True
            assert config.sentiment.bias_bullish_threshold == 0.2
            assert config.telegram.bot_token == "test_token"
            assert config.redis.host == "localhost"
            assert config.database.sqlite_path == "data/lohi_trade.db"
            assert config.logging.level == "INFO"
            assert config.paper_trading.enabled is False
            assert len(config.symbols) == 2
            assert "RELIANCE" in config.symbols
            
        finally:
            Path(temp_config_path).unlink()
            # Clean up environment variables
            for var in ['SHOONYA_API_KEY', 'SHOONYA_CLIENT_ID', 'SHOONYA_PASSWORD',
                       'ANGELONE_API_KEY', 'ANGELONE_CLIENT_ID', 'ANGELONE_PASSWORD',
                       'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']:
                if var in os.environ:
                    del os.environ[var]
    
    def test_load_config_missing_file(self):
        """Test that loading non-existent config file raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            load_config('nonexistent_config.yaml')
        assert 'not found' in str(exc_info.value)
    
    def test_load_config_missing_capital_section(self):
        """Test that missing capital section raises error."""
        config_content = """
risk_limits:
  max_open_positions: 5
"""
        temp_config_path = self.create_temp_config(config_content)
        
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                load_config(temp_config_path)
            assert 'capital' in str(exc_info.value).lower()
        finally:
            Path(temp_config_path).unlink()
    
    def test_load_config_invalid_capital_total(self):
        """Test that invalid capital total raises error."""
        config_content = """
capital:
  total: -100000
  risk_per_trade_pct: 1.0
  max_position_size_pct: 20.0
  max_daily_loss_pct: 2.0
"""
        temp_config_path = self.create_temp_config(config_content)
        
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                load_config(temp_config_path)
            assert 'positive number' in str(exc_info.value)
        finally:
            Path(temp_config_path).unlink()
    
    def test_load_config_invalid_percentage(self):
        """Test that invalid percentage raises error."""
        config_content = """
capital:
  total: 200000
  risk_per_trade_pct: 150.0
  max_position_size_pct: 20.0
  max_daily_loss_pct: 2.0
"""
        temp_config_path = self.create_temp_config(config_content)
        
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                load_config(temp_config_path)
            assert 'percentage' in str(exc_info.value)
        finally:
            Path(temp_config_path).unlink()
    
    def test_load_config_invalid_time_format(self):
        """Test that invalid time format raises error."""
        os.environ['SHOONYA_API_KEY'] = 'test'
        os.environ['SHOONYA_CLIENT_ID'] = 'test'
        os.environ['SHOONYA_PASSWORD'] = 'test'
        os.environ['ANGELONE_API_KEY'] = 'test'
        os.environ['ANGELONE_CLIENT_ID'] = 'test'
        os.environ['ANGELONE_PASSWORD'] = 'test'
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test'
        os.environ['TELEGRAM_CHAT_ID'] = 'test'
        
        config_content = """
capital:
  total: 200000
  risk_per_trade_pct: 1.0
  max_position_size_pct: 20.0
  max_daily_loss_pct: 2.0

risk_limits:
  max_open_positions: 5
  max_orders_per_day: 20
  cooldown_after_loss_minutes: 5
  volatility_guard_threshold_pct: 2.0
  volatility_guard_window_minutes: 10

trading_hours:
  market_open: "9:15"
  trading_start: "09:30"
  trading_end: "15:10"
  square_off_time: "15:15"
  market_close: "15:30"

broker:
  primary: "shoonya"
  backup: "angelone"
  shoonya:
    api_key: "${SHOONYA_API_KEY}"
    client_id: "${SHOONYA_CLIENT_ID}"
    password: "${SHOONYA_PASSWORD}"
  angelone:
    api_key: "${ANGELONE_API_KEY}"
    client_id: "${ANGELONE_CLIENT_ID}"
    password: "${ANGELONE_PASSWORD}"

strategies:
  mean_reversion:
    enabled: true
    rsi_oversold: 30
    rsi_overbought: 65
    volume_multiplier: 1.5
    stop_loss_atr_multiplier: 1.5
  trend_following:
    enabled: true
    ema_fast: 9
    ema_slow: 21
    stop_loss_atr_multiplier: 2.0
    target_atr_multiplier: 3.0
  opening_range_breakout:
    enabled: true
    range_start: "09:15"
    range_end: "09:30"
    trade_window_start: "09:30"
    trade_window_end: "10:30"
    volume_multiplier: 2.0
    target_multiplier: 1.5

sentiment:
  bias_bullish_threshold: 0.2
  bias_bearish_threshold: -0.2
  time_decay_half_life_hours: 4.0
  lookback_hours: 24
  recalculation_interval_minutes: 5

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
  rate_limit_messages_per_hour: 20

redis:
  host: "localhost"
  port: 6379
  db: 0

database:
  sqlite_path: "data/lohi_trade.db"
  duckdb_path: "data/historical.duckdb"
  backup_path: "data/backups"
  backup_time: "16:00"

logging:
  level: "INFO"
  log_dir: "data/logs"
  max_file_size_mb: 100
  backup_count: 10

paper_trading:
  enabled: false
  simulated_fill_delay_ms: [100, 500]
  simulated_slippage_pct: 0.05

symbols:
  - "RELIANCE"
"""
        temp_config_path = self.create_temp_config(config_content)
        
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                load_config(temp_config_path)
            assert 'time format' in str(exc_info.value).lower()
        finally:
            Path(temp_config_path).unlink()
            for var in ['SHOONYA_API_KEY', 'SHOONYA_CLIENT_ID', 'SHOONYA_PASSWORD',
                       'ANGELONE_API_KEY', 'ANGELONE_CLIENT_ID', 'ANGELONE_PASSWORD',
                       'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']:
                if var in os.environ:
                    del os.environ[var]
    
    def test_load_config_invalid_logging_level(self):
        """Test that invalid logging level raises error."""
        os.environ['SHOONYA_API_KEY'] = 'test'
        os.environ['SHOONYA_CLIENT_ID'] = 'test'
        os.environ['SHOONYA_PASSWORD'] = 'test'
        os.environ['ANGELONE_API_KEY'] = 'test'
        os.environ['ANGELONE_CLIENT_ID'] = 'test'
        os.environ['ANGELONE_PASSWORD'] = 'test'
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test'
        os.environ['TELEGRAM_CHAT_ID'] = 'test'
        
        config_content = """
capital:
  total: 200000
  risk_per_trade_pct: 1.0
  max_position_size_pct: 20.0
  max_daily_loss_pct: 2.0

risk_limits:
  max_open_positions: 5
  max_orders_per_day: 20
  cooldown_after_loss_minutes: 5
  volatility_guard_threshold_pct: 2.0
  volatility_guard_window_minutes: 10

trading_hours:
  market_open: "09:15"
  trading_start: "09:30"
  trading_end: "15:10"
  square_off_time: "15:15"
  market_close: "15:30"

broker:
  primary: "shoonya"
  backup: "angelone"
  shoonya:
    api_key: "${SHOONYA_API_KEY}"
    client_id: "${SHOONYA_CLIENT_ID}"
    password: "${SHOONYA_PASSWORD}"
  angelone:
    api_key: "${ANGELONE_API_KEY}"
    client_id: "${ANGELONE_CLIENT_ID}"
    password: "${ANGELONE_PASSWORD}"

strategies:
  mean_reversion:
    enabled: true
    rsi_oversold: 30
    rsi_overbought: 65
    volume_multiplier: 1.5
    stop_loss_atr_multiplier: 1.5
  trend_following:
    enabled: true
    ema_fast: 9
    ema_slow: 21
    stop_loss_atr_multiplier: 2.0
    target_atr_multiplier: 3.0
  opening_range_breakout:
    enabled: true
    range_start: "09:15"
    range_end: "09:30"
    trade_window_start: "09:30"
    trade_window_end: "10:30"
    volume_multiplier: 2.0
    target_multiplier: 1.5

sentiment:
  bias_bullish_threshold: 0.2
  bias_bearish_threshold: -0.2
  time_decay_half_life_hours: 4.0
  lookback_hours: 24
  recalculation_interval_minutes: 5

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
  rate_limit_messages_per_hour: 20

redis:
  host: "localhost"
  port: 6379
  db: 0

database:
  sqlite_path: "data/lohi_trade.db"
  duckdb_path: "data/historical.duckdb"
  backup_path: "data/backups"
  backup_time: "16:00"

logging:
  level: "INVALID"
  log_dir: "data/logs"
  max_file_size_mb: 100
  backup_count: 10

paper_trading:
  enabled: false
  simulated_fill_delay_ms: [100, 500]
  simulated_slippage_pct: 0.05

symbols:
  - "RELIANCE"
"""
        temp_config_path = self.create_temp_config(config_content)
        
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                load_config(temp_config_path)
            assert 'logging level' in str(exc_info.value).lower()
        finally:
            Path(temp_config_path).unlink()
            for var in ['SHOONYA_API_KEY', 'SHOONYA_CLIENT_ID', 'SHOONYA_PASSWORD',
                       'ANGELONE_API_KEY', 'ANGELONE_CLIENT_ID', 'ANGELONE_PASSWORD',
                       'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']:
                if var in os.environ:
                    del os.environ[var]
    
    def test_load_config_empty_symbols(self):
        """Test that empty symbols list raises error."""
        os.environ['SHOONYA_API_KEY'] = 'test'
        os.environ['SHOONYA_CLIENT_ID'] = 'test'
        os.environ['SHOONYA_PASSWORD'] = 'test'
        os.environ['ANGELONE_API_KEY'] = 'test'
        os.environ['ANGELONE_CLIENT_ID'] = 'test'
        os.environ['ANGELONE_PASSWORD'] = 'test'
        os.environ['TELEGRAM_BOT_TOKEN'] = 'test'
        os.environ['TELEGRAM_CHAT_ID'] = 'test'
        
        config_content = """
capital:
  total: 200000
  risk_per_trade_pct: 1.0
  max_position_size_pct: 20.0
  max_daily_loss_pct: 2.0

risk_limits:
  max_open_positions: 5
  max_orders_per_day: 20
  cooldown_after_loss_minutes: 5
  volatility_guard_threshold_pct: 2.0
  volatility_guard_window_minutes: 10

trading_hours:
  market_open: "09:15"
  trading_start: "09:30"
  trading_end: "15:10"
  square_off_time: "15:15"
  market_close: "15:30"

broker:
  primary: "shoonya"
  backup: "angelone"
  shoonya:
    api_key: "${SHOONYA_API_KEY}"
    client_id: "${SHOONYA_CLIENT_ID}"
    password: "${SHOONYA_PASSWORD}"
  angelone:
    api_key: "${ANGELONE_API_KEY}"
    client_id: "${ANGELONE_CLIENT_ID}"
    password: "${ANGELONE_PASSWORD}"

strategies:
  mean_reversion:
    enabled: true
    rsi_oversold: 30
    rsi_overbought: 65
    volume_multiplier: 1.5
    stop_loss_atr_multiplier: 1.5
  trend_following:
    enabled: true
    ema_fast: 9
    ema_slow: 21
    stop_loss_atr_multiplier: 2.0
    target_atr_multiplier: 3.0
  opening_range_breakout:
    enabled: true
    range_start: "09:15"
    range_end: "09:30"
    trade_window_start: "09:30"
    trade_window_end: "10:30"
    volume_multiplier: 2.0
    target_multiplier: 1.5

sentiment:
  bias_bullish_threshold: 0.2
  bias_bearish_threshold: -0.2
  time_decay_half_life_hours: 4.0
  lookback_hours: 24
  recalculation_interval_minutes: 5

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
  rate_limit_messages_per_hour: 20

redis:
  host: "localhost"
  port: 6379
  db: 0

database:
  sqlite_path: "data/lohi_trade.db"
  duckdb_path: "data/historical.duckdb"
  backup_path: "data/backups"
  backup_time: "16:00"

logging:
  level: "INFO"
  log_dir: "data/logs"
  max_file_size_mb: 100
  backup_count: 10

paper_trading:
  enabled: false
  simulated_fill_delay_ms: [100, 500]
  simulated_slippage_pct: 0.05

symbols: []
"""
        temp_config_path = self.create_temp_config(config_content)
        
        try:
            with pytest.raises(ConfigurationError) as exc_info:
                load_config(temp_config_path)
            assert 'symbol' in str(exc_info.value).lower()
        finally:
            Path(temp_config_path).unlink()
            for var in ['SHOONYA_API_KEY', 'SHOONYA_CLIENT_ID', 'SHOONYA_PASSWORD',
                       'ANGELONE_API_KEY', 'ANGELONE_CLIENT_ID', 'ANGELONE_PASSWORD',
                       'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']:
                if var in os.environ:
                    del os.environ[var]
