const { app, BrowserWindow } = require("electron");

function createWindow() {
  const win = new BrowserWindow({
    width: 900,
    height: 700,
    webPreferences: {
      contextIsolation: true
    }
  });

  win.loadURL("http://localhost:5000");
}

app.whenReady().then(createWindow);
