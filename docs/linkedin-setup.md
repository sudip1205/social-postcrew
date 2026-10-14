# Connect LinkedIn

Postcrew publishes only through LinkedIn's official API, to your own profile. You need a free LinkedIn
developer app; it takes about 5 minutes and you only do it once.

## 1. Create the app

1. Open [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) and click **Create app**.
2. Fill in a name (for example "Postcrew - your name"), and pick a **LinkedIn Page**. Every developer app must
   be linked to a Page. If you don't have one, LinkedIn lets you create a free Page in a minute.
3. Upload any logo, accept the terms and create the app.

## 2. Add the two products

On the app's **Products** tab, request:

- **Share on LinkedIn** (lets the app post as you: scope `w_member_social`)
- **Sign In with LinkedIn using OpenID Connect** (lets the app see who you are: scopes `openid profile`)

Both are approved instantly for personal use.

## 3. Add the redirect URL

On the **Auth** tab, under **Authorized redirect URLs for your app**, add exactly:

```
http://localhost:8765/oauth/callback
```

If you run the Studio on another port (`serve --port 9000`), use that port instead. The Credentials page
shows the exact URL to paste.

## 4. Paste the app details into Postcrew

Still on the **Auth** tab, copy the **Client ID** and **Client Secret**. In the Studio, open **Credentials**,
paste them under **LinkedIn app** and click **Save app details**.

The secret is written to `workspace/secrets.json` (readable only by your user account). The Studio can set
secrets but never sends them back to the browser.

## 5. Connect

Click **Connect LinkedIn**, sign in to LinkedIn and click **Allow**. You come back to the Studio with
"Connected as *your name*" and the date the token expires.

## Token expiry

LinkedIn tokens for personal apps last about 60 days and cannot be refreshed automatically. Postcrew's
Credential Monitor (Aegis) checks the token every day and before every publish. It notifies you a few days
before it expires (7 by default, see `notifications.warn_days_before_expiry`), and again if LinkedIn rejects
it. To renew it, click **Reconnect LinkedIn** on Credentials; it takes ten seconds.

If the token is invalid at post time, the post is **not** lost: it stays in the queue and goes out at the
next publish check after you reconnect.

## The first comment

LinkedIn shows posts with links in the body to fewer people, so the Formatter moves the primary source link
into a **first comment**. Right after the post is published, the Publisher adds that comment. If LinkedIn
refuses it (this happens when a post is only seconds old), it retries after 5 and 20 seconds, then at the
next two publish checks (every 15 minutes). After the last failed try you get a notification to add it by
hand. The **Published** table in the Queue shows whether each first comment was added.

You can change the first comment of any queued post with **Edit** in the Queue.

## Disconnecting

**Credentials > Disconnect** deletes the token from your workspace. To revoke the app's access on
LinkedIn's side as well, open LinkedIn **Settings > Data privacy > Permitted services** and remove the app.

## What Postcrew does and does not do on LinkedIn

It creates posts (text plus one image or video) on your profile and adds the first comment to those posts.
It does not read your feed, message anyone, like, connect, comment on other posts or scrape anything.
