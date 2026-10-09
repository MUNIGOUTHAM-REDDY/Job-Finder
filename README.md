# Job Finder

Telegram alerts for fresh, low-competition UI/UX, product, visual and design-engineering roles (India + remote).

| Part | Runs on | How often |
|---|---|---|
| Company careers pages (Greenhouse, Lever, Ashby, SmartRecruiters) + Remotive, RemoteOK, Hirist, Foundit, Cutshort, Wellfound | GitHub Actions | every 15 min, day and night |
| LinkedIn (logged-out search) + Naukri (Chrome on a virtual screen) | GitHub Actions | every 10 min, day and night |
| LinkedIn + Naukri (same, optional backup) | your Mac | every 10 min while awake, every 2 h at night |

- Filters and companies: `config.json`
- Test an alert: `.venv/bin/python run.py --test`
- Cloud runs: `.github/workflows/`; seen jobs are saved in `state/`
- Mac schedule: `./install_mac.sh` (remove with `./install_mac.sh --uninstall`), log in `logs/mac.log`
