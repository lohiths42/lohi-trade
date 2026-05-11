"""Configuration management for LOHI-TRADE system."""

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Ensure src is importable for market profile
_src_root = str(Path(__file__).resolve().parents[1])
if _src_root not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing required fields."""



@dataclass
class CapitalConfig:
    """Capital and risk configuration."""

    total: float
    risk_per_trade_pct: float
    max_position_size_pct: float
    max_daily_loss_pct: float


@dataclass
class RiskLimitsConfig:
    """Risk management limits."""

    max_open_positions: int
    max_orders_per_day: int
    cooldown_after_loss_minutes: int
    volatility_guard_threshold_pct: float
    volatility_guard_window_minutes: int


@dataclass
class TradingHoursConfig:
    """Trading hours configuration."""

    market_open: str
    trading_start: str
    trading_end: str
    square_off_time: str
    market_close: str


@dataclass
class BrokerCredentials:
    """Broker API credentials."""

    api_key: str
    client_id: str
    password: str


@dataclass
class BrokerConfig:
    """Broker configuration."""

    primary: str
    backup: str
    shoonya: BrokerCredentials
    angelone: BrokerCredentials


@dataclass
class MeanReversionStrategy:
    """Mean reversion strategy parameters."""

    enabled: bool
    rsi_oversold: int
    rsi_overbought: int
    volume_multiplier: float
    stop_loss_atr_multiplier: float


@dataclass
class TrendFollowingStrategy:
    """Trend following strategy parameters."""

    enabled: bool
    ema_fast: int
    ema_slow: int
    stop_loss_atr_multiplier: float
    target_atr_multiplier: float


@dataclass
class OpeningRangeBreakoutStrategy:
    """Opening range breakout strategy parameters."""

    enabled: bool
    range_start: str
    range_end: str
    trade_window_start: str
    trade_window_end: str
    volume_multiplier: float
    target_multiplier: float


@dataclass
class VWAPBounceStrategy:
    """VWAP Bounce strategy parameters."""

    enabled: bool = True
    rsi_min: float = 40.0
    rsi_max: float = 60.0
    vwap_proximity_pct: float = 0.3
    volume_multiplier: float = 1.2
    stop_loss_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 2.5


@dataclass
class StochasticRSIStrategy:
    """Stochastic + RSI combo strategy parameters."""

    enabled: bool = True
    stoch_oversold: float = 20.0
    stoch_overbought: float = 80.0
    rsi_oversold: float = 35.0
    rsi_overbought: float = 65.0
    stop_loss_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 2.5


@dataclass
class ADXTrendStrategy:
    """ADX Trend Strength strategy parameters."""

    enabled: bool = True
    adx_threshold: float = 25.0
    di_crossover_required: bool = True
    volume_multiplier: float = 1.0
    stop_loss_atr_multiplier: float = 2.0
    target_atr_multiplier: float = 3.0


@dataclass
class BollingerSqueezeStrategy:
    """Bollinger Band Squeeze strategy parameters."""

    enabled: bool = True
    squeeze_bb_width_threshold: float = 0.02
    breakout_volume_multiplier: float = 1.5
    stop_loss_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 3.0


@dataclass
class PivotPointStrategy:
    """Pivot Point support/resistance strategy parameters."""

    enabled: bool = True
    proximity_pct: float = 0.2
    volume_multiplier: float = 1.0
    stop_loss_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 2.0


@dataclass
class IchimokuCloudStrategy:
    """Ichimoku Cloud strategy parameters."""

    enabled: bool = True
    require_price_above_cloud: bool = True
    require_tenkan_kijun_cross: bool = True
    stop_loss_atr_multiplier: float = 2.0
    target_atr_multiplier: float = 3.0


@dataclass
class MACDDivergenceStrategy:
    """MACD Divergence strategy parameters."""

    enabled: bool = True
    lookback_candles: int = 10
    rsi_confirmation: bool = True
    stop_loss_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 3.0


@dataclass
class ParabolicSARTrendStrategy:
    """Parabolic SAR + EMA trend strategy parameters."""

    enabled: bool = True
    require_ema_alignment: bool = True
    volume_multiplier: float = 1.0
    stop_loss_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 2.5


@dataclass
class VolumeBreakoutStrategy:
    """Volume-confirmed breakout strategy parameters."""

    enabled: bool = True
    volume_spike_multiplier: float = 2.5
    price_breakout_pct: float = 0.5
    lookback_candles: int = 20
    stop_loss_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 3.0


@dataclass
class MultiTimeframeMomentumStrategy:
    """Multi-indicator momentum confluence strategy parameters."""

    enabled: bool = True
    min_indicators_aligned: int = 5
    stop_loss_atr_multiplier: float = 2.0
    target_atr_multiplier: float = 3.0


@dataclass
class StrategiesConfig:
    """Trading strategies configuration."""

    mean_reversion: MeanReversionStrategy
    trend_following: TrendFollowingStrategy
    opening_range_breakout: OpeningRangeBreakoutStrategy
    vwap_bounce: VWAPBounceStrategy | None = None
    stochastic_rsi: StochasticRSIStrategy | None = None
    adx_trend: ADXTrendStrategy | None = None
    bollinger_squeeze: BollingerSqueezeStrategy | None = None
    pivot_point: PivotPointStrategy | None = None
    ichimoku_cloud: IchimokuCloudStrategy | None = None
    macd_divergence: MACDDivergenceStrategy | None = None
    parabolic_sar_trend: ParabolicSARTrendStrategy | None = None
    volume_breakout: VolumeBreakoutStrategy | None = None
    multi_timeframe_momentum: MultiTimeframeMomentumStrategy | None = None


@dataclass
class SentimentConfig:
    """Sentiment analysis configuration."""

    bias_bullish_threshold: float
    bias_bearish_threshold: float
    time_decay_half_life_hours: float
    lookback_hours: int
    recalculation_interval_minutes: int


@dataclass
class TelegramConfig:
    """Telegram notification configuration."""

    bot_token: str
    chat_id: str
    rate_limit_messages_per_hour: int


@dataclass
class RedisConfig:
    """Redis configuration."""

    host: str
    port: int
    db: int


@dataclass
class DatabaseConfig:
    """Database configuration."""

    sqlite_path: str
    duckdb_path: str
    backup_path: str
    backup_time: str


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str
    log_dir: str
    max_file_size_mb: int
    backup_count: int


@dataclass
class PaperTradingConfig:
    """Paper trading configuration."""

    enabled: bool
    simulated_fill_delay_ms: list[int]
    simulated_slippage_pct: float


@dataclass
class MLStrategyConfig:
    """ML strategy configuration."""

    enabled: bool = True
    confidence_threshold: float = 0.55
    min_training_samples: int = 30
    retrain_threshold: int = 20
    passthrough_when_untrained: bool = True
    model_dir: str = "data/ml_models"


@dataclass
class MarketConfig:
    """Market/country configuration loaded from config/market.yaml.

    This provides the trading engine with country-specific settings
    without requiring the full MarketProfile Pydantic model at runtime.
    """

    country: str = "IN"
    country_name: str = "India"
    currency: str = "INR"
    currency_symbol: str = "₹"
    timezone: str = "Asia/Kolkata"
    primary_exchange: str = "NSE"
    benchmark_index_name: str = "Nifty 50"
    benchmark_symbol: str = "^NSEI"
    benchmark_redis_key: str = "nifty"
    settlement_cycle: str = "T+1"
    data_suffix: str = ".NS"
    number_format: str = "indian"  # "indian", "international", "european"


@dataclass
class Config:
    """Main configuration class."""

    capital: CapitalConfig
    risk_limits: RiskLimitsConfig
    trading_hours: TradingHoursConfig
    broker: BrokerConfig
    strategies: StrategiesConfig
    sentiment: SentimentConfig
    telegram: TelegramConfig
    redis: RedisConfig
    database: DatabaseConfig
    logging: LoggingConfig
    paper_trading: PaperTradingConfig
    symbols: list[str]
    ml_strategy: MLStrategyConfig = None
    market: MarketConfig = None

    def __post_init__(self):
        if self.ml_strategy is None:
            self.ml_strategy = MLStrategyConfig()
        if self.market is None:
            self.market = self._load_market_config()

    def _load_market_config(self) -> MarketConfig:
        """Load market config from config/market.yaml if it exists."""
        market_path = Path("config/market.yaml")
        if not market_path.exists():
            # Default to India (backward compatible)
            return MarketConfig()

        try:
            with open(market_path) as f:
                data = yaml.safe_load(f)
            if not data:
                return MarketConfig()

            return MarketConfig(
                country=data.get("country", "IN"),
                country_name=data.get("country_name", "India"),
                currency=data.get("currency", "INR"),
                currency_symbol=data.get("currency_symbol", "₹"),
                timezone=data.get("timezone", "Asia/Kolkata"),
                primary_exchange=data.get("primary_exchange", "NSE"),
                benchmark_index_name=data.get("benchmark_index", "Nifty 50"),
                benchmark_symbol=data.get("benchmark_symbol", "^NSEI"),
                benchmark_redis_key=data.get("benchmark_redis_key", "nifty"),
                settlement_cycle=data.get("settlement_cycle", "T+1"),
                data_suffix=data.get("data_suffix", ".NS"),
                number_format=data.get("number_format", "indian"),
            )
        except (yaml.YAMLError, OSError):
            return MarketConfig()


def substitute_env_vars(value: Any) -> Any:
    """Recursively substitute environment variables in configuration values.
    
    Environment variables are specified as ${VAR_NAME} in the YAML file.
    
    Args:
        value: Configuration value (can be dict, list, str, or other types)
        
    Returns:
        Value with environment variables substituted
        
    Raises:
        ConfigurationError: If environment variable is not set

    """
    if isinstance(value, str):
        # Pattern to match ${VAR_NAME}
        pattern = r"\$\{([^}]+)\}"
        matches = re.findall(pattern, value)

        for var_name in matches:
            env_value = os.getenv(var_name)
            if env_value is None:
                raise ConfigurationError(
                    f"Environment variable '{var_name}' is not set. "
                    f"Please set it before starting the system.",
                )
            value = value.replace(f"${{{var_name}}}", env_value)

        return value

    if isinstance(value, dict):
        return {k: substitute_env_vars(v) for k, v in value.items()}

    if isinstance(value, list):
        return [substitute_env_vars(item) for item in value]

    return value


def validate_time_format(time_str: str, field_name: str) -> None:
    """Validate time string is in HH:MM format.
    
    Args:
        time_str: Time string to validate
        field_name: Name of the field for error messages
        
    Raises:
        ConfigurationError: If time format is invalid

    """
    pattern = r"^([0-1][0-9]|2[0-3]):[0-5][0-9]$"
    if not re.match(pattern, time_str):
        raise ConfigurationError(
            f"Invalid time format for '{field_name}': '{time_str}'. "
            f"Expected format: HH:MM (e.g., '09:30')",
        )


def validate_required_fields(data: dict[str, Any], required_fields: list[str], section: str) -> None:
    """Validate that all required fields are present in configuration section.
    
    Args:
        data: Configuration data dictionary
        required_fields: List of required field names
        section: Name of the configuration section for error messages
        
    Raises:
        ConfigurationError: If any required field is missing

    """
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        raise ConfigurationError(
            f"Missing required fields in '{section}' section: {', '.join(missing_fields)}",
        )


def validate_positive_number(value: Any, field_name: str) -> None:
    """Validate that a value is a positive number.
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        
    Raises:
        ConfigurationError: If value is not a positive number

    """
    if not isinstance(value, (int, float)) or value <= 0:
        raise ConfigurationError(
            f"Field '{field_name}' must be a positive number, got: {value}",
        )


def validate_percentage(value: Any, field_name: str) -> None:
    """Validate that a value is a valid percentage (0-100).
    
    Args:
        value: Value to validate
        field_name: Name of the field for error messages
        
    Raises:
        ConfigurationError: If value is not a valid percentage

    """
    if not isinstance(value, (int, float)) or value < 0 or value > 100:
        raise ConfigurationError(
            f"Field '{field_name}' must be a percentage between 0 and 100, got: {value}",
        )


def load_config(config_path: str = "config/settings.yaml") -> Config:
    """Load and validate configuration from YAML file.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Validated Config object
        
    Raises:
        ConfigurationError: If configuration is invalid or missing required fields

    """
    # Check if file exists
    if not Path(config_path).exists():
        raise ConfigurationError(
            f"Configuration file not found: {config_path}. "
            f"Please create it from config/settings.yaml.template",
        )

    # Load YAML file
    try:
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Failed to parse YAML configuration: {e}")

    if not raw_config:
        raise ConfigurationError("Configuration file is empty")

    # Substitute environment variables
    try:
        raw_config = substitute_env_vars(raw_config)
    except ConfigurationError:
        raise

    # Validate and build configuration objects
    try:
        # Capital configuration
        validate_required_fields(
            raw_config.get("capital", {}),
            ["total", "risk_per_trade_pct", "max_position_size_pct", "max_daily_loss_pct"],
            "capital",
        )
        capital_data = raw_config["capital"]
        validate_positive_number(capital_data["total"], "capital.total")
        validate_percentage(capital_data["risk_per_trade_pct"], "capital.risk_per_trade_pct")
        validate_percentage(capital_data["max_position_size_pct"], "capital.max_position_size_pct")
        validate_percentage(capital_data["max_daily_loss_pct"], "capital.max_daily_loss_pct")

        capital = CapitalConfig(**capital_data)

        # Risk limits configuration
        validate_required_fields(
            raw_config.get("risk_limits", {}),
            ["max_open_positions", "max_orders_per_day", "cooldown_after_loss_minutes",
             "volatility_guard_threshold_pct", "volatility_guard_window_minutes"],
            "risk_limits",
        )
        risk_limits_data = raw_config["risk_limits"]
        risk_limits = RiskLimitsConfig(**risk_limits_data)

        # Trading hours configuration
        validate_required_fields(
            raw_config.get("trading_hours", {}),
            ["market_open", "trading_start", "trading_end", "square_off_time", "market_close"],
            "trading_hours",
        )
        trading_hours_data = raw_config["trading_hours"]
        for field in ["market_open", "trading_start", "trading_end", "square_off_time", "market_close"]:
            validate_time_format(trading_hours_data[field], f"trading_hours.{field}")

        trading_hours = TradingHoursConfig(**trading_hours_data)

        # Broker configuration
        validate_required_fields(
            raw_config.get("broker", {}),
            ["primary", "backup", "shoonya", "angelone"],
            "broker",
        )
        broker_data = raw_config["broker"]

        # Validate broker credentials
        for broker_name in ["shoonya", "angelone"]:
            validate_required_fields(
                broker_data.get(broker_name, {}),
                ["api_key", "client_id", "password"],
                f"broker.{broker_name}",
            )

        shoonya_creds = BrokerCredentials(**broker_data["shoonya"])
        angelone_creds = BrokerCredentials(**broker_data["angelone"])

        broker = BrokerConfig(
            primary=broker_data["primary"],
            backup=broker_data["backup"],
            shoonya=shoonya_creds,
            angelone=angelone_creds,
        )

        # Strategies configuration
        validate_required_fields(
            raw_config.get("strategies", {}),
            ["mean_reversion", "trend_following", "opening_range_breakout"],
            "strategies",
        )
        strategies_data = raw_config["strategies"]

        mean_reversion = MeanReversionStrategy(**strategies_data["mean_reversion"])
        trend_following = TrendFollowingStrategy(**strategies_data["trend_following"])
        opening_range_breakout = OpeningRangeBreakoutStrategy(**strategies_data["opening_range_breakout"])

        strategies = StrategiesConfig(
            mean_reversion=mean_reversion,
            trend_following=trend_following,
            opening_range_breakout=opening_range_breakout,
            vwap_bounce=VWAPBounceStrategy(**strategies_data["vwap_bounce"]) if "vwap_bounce" in strategies_data else VWAPBounceStrategy(),
            stochastic_rsi=StochasticRSIStrategy(**strategies_data["stochastic_rsi"]) if "stochastic_rsi" in strategies_data else StochasticRSIStrategy(),
            adx_trend=ADXTrendStrategy(**strategies_data["adx_trend"]) if "adx_trend" in strategies_data else ADXTrendStrategy(),
            bollinger_squeeze=BollingerSqueezeStrategy(**strategies_data["bollinger_squeeze"]) if "bollinger_squeeze" in strategies_data else BollingerSqueezeStrategy(),
            pivot_point=PivotPointStrategy(**strategies_data["pivot_point"]) if "pivot_point" in strategies_data else PivotPointStrategy(),
            ichimoku_cloud=IchimokuCloudStrategy(**strategies_data["ichimoku_cloud"]) if "ichimoku_cloud" in strategies_data else IchimokuCloudStrategy(),
            macd_divergence=MACDDivergenceStrategy(**strategies_data["macd_divergence"]) if "macd_divergence" in strategies_data else MACDDivergenceStrategy(),
            parabolic_sar_trend=ParabolicSARTrendStrategy(**strategies_data["parabolic_sar_trend"]) if "parabolic_sar_trend" in strategies_data else ParabolicSARTrendStrategy(),
            volume_breakout=VolumeBreakoutStrategy(**strategies_data["volume_breakout"]) if "volume_breakout" in strategies_data else VolumeBreakoutStrategy(),
            multi_timeframe_momentum=MultiTimeframeMomentumStrategy(**strategies_data["multi_timeframe_momentum"]) if "multi_timeframe_momentum" in strategies_data else MultiTimeframeMomentumStrategy(),
        )

        # Sentiment configuration
        validate_required_fields(
            raw_config.get("sentiment", {}),
            ["bias_bullish_threshold", "bias_bearish_threshold", "time_decay_half_life_hours",
             "lookback_hours", "recalculation_interval_minutes"],
            "sentiment",
        )
        sentiment = SentimentConfig(**raw_config["sentiment"])

        # Telegram configuration
        validate_required_fields(
            raw_config.get("telegram", {}),
            ["bot_token", "chat_id", "rate_limit_messages_per_hour"],
            "telegram",
        )
        telegram = TelegramConfig(**raw_config["telegram"])

        # Redis configuration
        validate_required_fields(
            raw_config.get("redis", {}),
            ["host", "port", "db"],
            "redis",
        )
        redis = RedisConfig(**raw_config["redis"])

        # Database configuration
        validate_required_fields(
            raw_config.get("database", {}),
            ["sqlite_path", "duckdb_path", "backup_path", "backup_time"],
            "database",
        )
        database = DatabaseConfig(**raw_config["database"])

        # Logging configuration
        validate_required_fields(
            raw_config.get("logging", {}),
            ["level", "log_dir", "max_file_size_mb", "backup_count"],
            "logging",
        )
        logging_data = raw_config["logging"]
        if logging_data["level"] not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            raise ConfigurationError(
                f"Invalid logging level: {logging_data['level']}. "
                f"Must be one of: DEBUG, INFO, WARNING, ERROR",
            )
        logging = LoggingConfig(**logging_data)

        # Paper trading configuration
        validate_required_fields(
            raw_config.get("paper_trading", {}),
            ["enabled", "simulated_fill_delay_ms", "simulated_slippage_pct"],
            "paper_trading",
        )
        paper_trading = PaperTradingConfig(**raw_config["paper_trading"])

        # Symbols
        if "symbols" not in raw_config or not raw_config["symbols"]:
            raise ConfigurationError("At least one symbol must be configured in 'symbols' list")
        symbols = raw_config["symbols"]

        # ML Strategy configuration (optional, defaults if missing)
        ml_strategy_data = raw_config.get("ml_strategy", {})
        ml_strategy = MLStrategyConfig(**ml_strategy_data) if ml_strategy_data else MLStrategyConfig()

        # Build final config
        config = Config(
            capital=capital,
            risk_limits=risk_limits,
            trading_hours=trading_hours,
            broker=broker,
            strategies=strategies,
            sentiment=sentiment,
            telegram=telegram,
            redis=redis,
            database=database,
            logging=logging,
            paper_trading=paper_trading,
            symbols=symbols,
            ml_strategy=ml_strategy,
        )

        return config

    except KeyError as e:
        raise ConfigurationError(f"Missing required configuration field: {e}")
    except TypeError as e:
        raise ConfigurationError(f"Invalid configuration data type: {e}")


# Global configuration instance
_config: Config = None


def get_config(config_path: str = "config/settings.yaml") -> Config:
    """Get the global configuration instance.
    
    Loads configuration on first call and caches it for subsequent calls.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Config object

    """
    global _config
    if _config is None:
        _config = load_config(config_path)
    return _config


def reload_config(config_path: str = "config/settings.yaml") -> Config:
    """Reload configuration from file.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Reloaded Config object

    """
    global _config
    _config = load_config(config_path)
    return _config
