# Connect YouTube

Postcrew uploads through YouTube's official Data API, with a Google OAuth app you create once (about 10 minutes, free). It uploads
to **your** channel and does nothing else: no comments, no subscribing, no scraping.

## 1. Create the Google app

1. Open [console.cloud.google.com](https://console.cloud.google.com) and create a project (any name).
2. **APIs & Services > Library**: enable **YouTube Data API v3**.
3. **APIs & Services > OAuth consent screen**: choose **External**, fill the app name and your email, and add yourself under
   **Test users** (your Google account, the one that owns the channel). Scopes: `youtube.upload` and `youtube.readonly`.
4. **Credentials > Create credentials > OAuth client ID > Web application**. Under **Authorized redirect URIs** add exactly the
   address shown in Studio > Credentials > YouTube (by default `http://localhost:8765/oauth/youtube/callback`).
5. Copy the **Client ID** and **Client secret**.

## 2. Connect it

Studio > **Credentials** > YouTube: paste the client ID and secret, click **Save app details**, then **Connect YouTube** and sign in.
The Studio shows the channel name when it works. `postcrew doctor` also reports it.

## What to expect

- **Unverified apps upload as private.** Google restricts apps that have not passed its audit: a video uploaded through a
  test-mode app can be forced to `private` and cannot go public by itself. Either set the video public by hand in YouTube Studio,
  or complete Google's OAuth verification and the YouTube API Services audit for your app. Postcrew uploads with the visibility
  you chose (Settings > YouTube > When a post is ready), and tells you what YouTube answered.
- **Daily quota.** A new project has 10,000 quota units a day and an upload costs about 1,600: roughly six uploads a day. When
  the quota is used up the video stays in the Queue and goes out the next day. Ask Google for more quota if you need it.
- **Custom thumbnails** need a verified channel (phone verification). If YouTube refuses the thumbnail, the video is still
  uploaded and the Studio says the thumbnail was not set.
- **Tokens.** Google tokens for apps in testing mode expire after 7 days. The Credential Monitor tells you when YouTube needs
  reconnecting; publishing the OAuth consent screen ("In production") removes that limit.
- Videos of 60 seconds or less in vertical format are Shorts automatically; Postcrew adds `#Shorts` to their description.

## Practice mode

Every app starts in **practice mode**: the crew makes the video and queues it, and the publisher only logs what it would upload.
Turn it off in Settings > YouTube when the first videos look right.


## Connecting from another computer, and when the sign-in keeps expiring

- **The last step says "This site can't be reached"**: that is expected when the Studio runs on another computer (such as the AI lab). Google sends the browser to `http://localhost:8765/oauth/youtube/callback?...`, and `localhost` is the computer you are sitting at. In Credentials, click **Connect YouTube**, allow access, **copy the whole address from the address bar** and paste it into **Finish connecting**. (Alternative: open an SSH tunnel with `ssh -L 8765:localhost:8765 user@lab` and use `http://localhost:8765` for the whole sign-in.)
- **The register-this-redirect step**: add exactly `http://localhost:8765/oauth/youtube/callback` (with your port) as an authorised redirect URI, never the lab's network address: Google does not accept a private address.
- **"Google rejected the YouTube connection" after a few days**: if the OAuth consent screen's *Publishing status* is **Testing**, Google expires the refresh token after 7 days. In Google Cloud Console open *APIs & Services > OAuth consent screen* and press **Publish app** (a personal app can stay unverified); the connection then no longer expires every week.
