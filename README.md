# Job Finder

Telegram alerts for fresh, low-competition UI/UX, product, visual and design-engineering roles (India + remote).

| Part | Runs on | How often |
|---|---|---|
| Company careers pages (Greenhouse, Lever, Ashby) + Remotive/RemoteOK | GitHub Actions | every 15 min |
| LinkedIn (logged-out search) + Naukri (off-screen Chrome) | your Mac | every 10 min while awake |

- Filters and companies: `config.json`
- Test an alert: `.venv/bin/python run.py --test`
- Mac schedule: `./install_mac.sh` (remove with `./install_mac.sh --uninstall`), log in `logs/mac.log`
