# Notifications

Postcrew tells you when something needs you: a post is ready or published, a day has no post (and why), a
LinkedIn token is about to expire or was rejected, publishing or a first comment failed, a team member was
replaced. The same warning is not repeated more than about once a day.

Every notification appears under the **bell** in the Studio. You can also get them on your desktop, by
email or on Telegram: turn the channels on in **Settings > Publishing and alerts**, and click **Send a
test** to check them.

## Desktop

On by default (`notifications.desktop`).

- **macOS**: Notification Center. The first time, macOS may ask you to allow notifications from Script
  Editor or your terminal app.
- **Linux**: uses `notify-send` (package `libnotify-bin` on Debian and Ubuntu).

Desktop notifications only work while you are logged in to that computer. On a server, use email or Telegram.

## Gmail

Postcrew sends email through your Gmail account with an **App Password**, a 16-character password that only
works for this one app. Your real Gmail password is never used.

1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification) for the
   Google account (App Passwords require it).
2. Open [App Passwords](https://myaccount.google.com/apppasswords), create one named "Postcrew" and copy the
   16 characters.
3. In the Studio, open **Credentials > Gmail notifications**. Enter the Gmail address, paste the App Password,
   and optionally a different address to send to. Click **Save Gmail**, then **Send a test email**.
4. Turn on **Gmail** in **Settings > Publishing and alerts** and save.

To revoke it, delete the App Password in your Google account.

## Telegram

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot` and follow the steps. Copy the
   **bot token** it gives you.
2. Open a chat with your new bot and send it any message (bots can't message you first).
3. Find your **chat id**: open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and look
   for `"chat":{"id":123456789`. That number is the chat id.
4. In the Studio, open **Credentials > Telegram notifications**, paste the token and the chat id, and click
   **Save Telegram**.
5. Turn on **Telegram** in **Settings > Publishing and alerts**, save, and click **Send a test**.

The bot token is a secret: anyone with it can send messages as your bot. It is stored only in
`workspace/secrets.json`.
