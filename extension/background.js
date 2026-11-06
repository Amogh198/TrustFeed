// Adds the right-click menu. The result window does the work, as a background worker can be
// stopped during a long check.
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'trustfeed', title: 'Check with TrustFeed', contexts: ['image', 'video', 'link', 'selection'] });
});

function openWindow() {
  chrome.windows.create({ url: chrome.runtime.getURL('result.html'), type: 'popup', width: 520, height: 720 });
}

chrome.contextMenus.onClicked.addListener(async info => {
  let item;
  if (info.mediaType === 'image' || info.mediaType === 'video') item = { kind: info.mediaType, url: info.srcUrl };
  else if (info.selectionText) item = { kind: 'text', text: info.selectionText };
  else if (info.linkUrl) item = { kind: 'link', url: info.linkUrl };
  if (!item) return;
  await chrome.storage.session.set({ pending: item });
  openWindow();
});

chrome.action.onClicked.addListener(async () => {
  await chrome.storage.session.remove('pending');
  openWindow();
});
