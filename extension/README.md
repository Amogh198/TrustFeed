# TrustFeed Chrome extension

1. Start the API on port 8000 and the dashboard on port 5173.
2. Open `chrome://extensions` and turn on **Developer mode**.
3. Click **Load unpacked** and choose this `extension` folder.
4. Right-click an image, video, link or selected text, and choose **Check with TrustFeed**. Or click the toolbar icon to paste something.

Nothing goes to outside services until you click **Also search the web**. The file or text does go to your TrustFeed server.

Limits: it needs the local server. Some sites block downloads, and streaming videos such as YouTube usually can't be fetched. Cases are saved as signed out, so anyone signed out on that server can see them. It reads whatever the right-clicked URL points to, which is why it asks for access to all sites.
