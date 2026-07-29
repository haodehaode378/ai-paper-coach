# AI Paper Coach Desktop

Windows 11 x64 desktop shell for the existing Vue frontend.

## Development

```powershell
npm install
npm run info
npm run dev
```

The development command builds the isolated FastAPI sidecar, starts the Vite app in `apps/web`, and opens it in a native window.

## Build

```powershell
npm run build
```

The production build creates an isolated Python build environment, packages FastAPI with PyInstaller, creates `apps/web/dist`, and bundles both with Tauri.

The desktop process allocates a random localhost port and a per-launch API token. User data is stored in the Windows application data directory. If a legacy `services/data` directory is found on first launch, missing files are copied to the new directory and the source is left untouched.

Build only the Windows NSIS installer:

```powershell
npm run build -- --bundles nsis
```

`dev-icon.svg` and the generated files under `src-tauri/icons` are development placeholders. Replace them with approved brand assets before public release.
