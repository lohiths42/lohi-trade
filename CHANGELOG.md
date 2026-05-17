# CHANGELOG

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial open source release
- Comprehensive CI/CD pipeline with GitHub Actions
- Documentation on contributing guidelines
- Audit reports for OSS readiness

### Changed
- Reorganized dependencies into optional groups (ml, backtesting, dashboard, nubra)
- Made pandas-ta gracefully optional for core trading functionality
- Updated README with optional features matrix

### Fixed
- Missing prometheus-client dependency declaration
- pandas-ta import error handling

## [0.1.0] - 2026-05-09

### Added
- Event-driven hybrid algorithmic trading system for Indian equity markets
- Multi-broker support (Shoonya, Angel One, Zerodha, Groww, Nubra.io)
- Dual-engine signal generation (technical + sentiment analysis)
- 9-point risk management system with kill switch
- Paper trading simulator
- React web dashboard with real-time updates
- REST API with 30+ endpoints
- Redis Streams event bus with at-least-once delivery
- PostgreSQL state layer with migrations
- FinBERT sentiment analysis via ONNX Runtime
- Technical indicators via ta-lib and pandas-ta
- Telegram notifications
- CLI commands (setup, start, stop, doctor, status)
- Comprehensive test suite (1474+ tests)
- Docker Compose infrastructure
- Support for Python 3.11, 3.12, 3.13

### Testing
- 1474 unit tests passing (97.7%)
- Property-based tests for critical paths
- 39% code coverage (60-90% for core modules)
- Integration tests for all brokers and risk management

### Documentation
- Complete audit report (OSS_AUDIT.md)
- Setup and installation guide (SETUP.md)
- Architecture documentation (docs/ARCHITECTURE.md)
- Contributing guidelines (CONTRIBUTING.md)
- API reference in docstrings
- Example strategies (mean reversion, ORB, trend following)

### Performance
- Backend startup: 2-3 seconds
- Full stack startup: 15-20 seconds
- Order latency: <500ms end-to-end
- Tick throughput: 1000+ ticks/second
- Memory footprint: 700-900 MB idle

---

## Release Notes

### v0.1.0 - Initial Release

**LOHI-TRADE is now publicly available as an open-source, MIT-licensed algorithmic trading platform for Indian equity markets.**

#### Key Features
- ✅ Fully functional event-driven trading engine
- ✅ Multi-broker support with paper trading fallback
- ✅ Real-time web dashboard
- ✅ Comprehensive risk management
- ✅ Optional AI-powered sentiment analysis
- ✅ Production-grade infrastructure (Docker, PostgreSQL, Redis)
- ✅ Extensive test suite (1474+ tests)
- ✅ Free to use with free alternatives for all paid services

#### Installation
```bash
pip install lohi-trade
lohi setup
lohi start
```

#### Documentation
- See [README.md](README.md) for quick start
- See [SETUP.md](SETUP.md) for detailed setup
- See [CONTRIBUTING.md](CONTRIBUTING.md) to contribute
- See [OSS_AUDIT.md](OSS_AUDIT.md) for audit findings

#### Support
- GitHub Issues for bug reports
- GitHub Discussions for Q&A
- Pull requests welcome!

---

## Future Roadmap

### v0.2.0 (Estimated Q3 2026)
- [ ] Web-based configuration UI
- [ ] More example strategies
- [ ] Broker-specific setup guides
- [ ] Helm charts for Kubernetes
- [ ] Additional technical indicators
- [ ] Improved mobile app support

### v0.3.0 (Estimated Q4 2026)
- [ ] Machine learning strategy optimizer
- [ ] Advanced backtesting features
- [ ] Multi-account management
- [ ] Cloud deployment guides
- [ ] Community strategy marketplace

### v1.0.0 (Estimated Q1 2027)
- [ ] Production-grade stability
- [ ] Enterprise features
- [ ] Commercial support options
- [ ] Certified brokers
- [ ] Trading course

---

## Notes

- All dates are estimates
- Roadmap subject to change based on community feedback
- Contributors are welcome to help with any feature
