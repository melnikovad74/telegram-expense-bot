# Free 24/7 deployment on Oracle Cloud

This deployment uses an Oracle Cloud Infrastructure Always Free VM and systemd. It runs the bot continuously, restarts it after a crash, and stores SQLite data under `/var/lib/telegram-expense-bot`.

## Important
- Oracle advertises Always Free compute resources, but account approval, payment-card verification, and regional capacity are controlled by Oracle. Availability is not guaranteed.
- Choose only a VM shape explicitly marked **Always Free eligible** in your Oracle console. Do not upgrade to a paid plan or select paid resources.
- Keep your bot token out of GitHub. Use a new token generated with @BotFather if the old one was ever shared.
- This script is intended for a fresh Ubuntu 22.04 or 24.04 VM.

## Steps
1. Create an Oracle Cloud account and an Always Free eligible Ubuntu VM.
2. Connect to the VM using SSH from a trusted device/app.
3. Clone this repository, enter its directory, then run:
   `chmod +x deploy/oracle/install.sh`
   `sudo ./deploy/oracle/install.sh`
4. Set the token securely:
   `sudo nano /etc/telegram-expense-bot.env`
   Replace `PASTE_NEW_TOKEN_HERE` with the new token. Save the file.
5. Start and verify:
   `sudo systemctl start telegram-expense-bot`
   `sudo systemctl status telegram-expense-bot --no-pager`
   `sudo journalctl -u telegram-expense-bot -n 50 --no-pager`

No inbound ports need to be opened for this bot because it uses Telegram long polling.
