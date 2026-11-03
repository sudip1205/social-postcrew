# Privacy Policy: Postcrew

*Last updated: 2 November 2026*

Postcrew is a self-hosted tool that writes and publishes posts and videos. It runs on the computer of the person who installs it (the "owner"). There is no Postcrew server, no Postcrew account, and nobody who develops Postcrew receives data from your installation.

## What Postcrew stores, and where

Everything is stored in the owner's own Postcrew workspace folder on the owner's own computer:

- the owner's Google OAuth client ID and client secret, and the YouTube sign-in token (a refresh token) that Google issues when the owner allows access;
- the name of the connected YouTube channel;
- the owner's LinkedIn sign-in token, if LinkedIn is connected;
- the posts, scripts, videos, plans and settings the owner creates.

None of this is sent to the developer of Postcrew or to any third party for the developer's use.

## Google user data

When the owner connects YouTube, Postcrew asks Google for two permissions:

- `youtube.upload`: to upload the videos the owner has chosen to publish, with the title, description, tags and thumbnail the owner approved;
- `youtube.readonly`: to read the name of the connected channel, to check that the connection still works.

Postcrew uses this access only to do what the owner asks. It does not read the owner's other videos, comments or analytics, does not sell or share Google user data, does not use it for advertising, and no person at Postcrew reads it. Postcrew's use and transfer of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

By connecting YouTube, the owner is also bound by the [YouTube Terms of Service](https://www.youtube.com/t/terms) and the [Google Privacy Policy](https://policies.google.com/privacy).

## Other services the owner chooses to use

The owner may connect an AI provider (for example Anthropic's Claude) and a voice provider (for example ElevenLabs) so that Postcrew can write scripts and read them aloud. Postcrew sends them the text of the content being made, under the owner's own account and that provider's terms. Postcrew also reads public YouTube and web pages to research topics. This does not involve the owner's Google account.

## Removing access and deleting data

- **Disconnect:** the owner can press *Disconnect* in Postcrew's Credentials page, which deletes the stored YouTube token.
- **Revoke at Google:** the owner can remove Postcrew's access at any time at <https://myaccount.google.com/permissions>.
- **Delete everything:** deleting the workspace folder deletes all data Postcrew holds.

## Contact

Questions about this policy can be raised as an issue at <https://github.com/sudip1205/social-postcrew/issues>.
