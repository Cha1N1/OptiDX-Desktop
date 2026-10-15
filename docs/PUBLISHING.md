# Publishing the Desktop source

Publish Desktop in its own repository. Keep
[Cha1N1/OptiDX](https://github.com/Cha1N1/OptiDX) for the original script.
`OptiDX-Desktop` is a suggested name for the new repository; it has not been
created by this work.

## What belongs in the source repository

- `optidx_desktop/`: application code and its small SVG asset set.
- `backend/`: adapted backend and original/current provenance records.
- `packaging/`: build scripts, AppRun wrappers, desktop entry and packaging icon.
- `tests/`: regression tests and synthetic fixtures.
- `docs/`: documentation and the public README screenshot.
- Root source/configuration files: README, license, release notes, contributor
  instructions, requirements, entrypoints and `.gitignore`.

The app icon and packaging icon serve different consumers. The checkbox and
chevron SVGs support app controls; `docs/screenshots/desktop.png` illustrates the
README. These are required source assets rather than generated icon caches.

Do not upload `build/`, `dist/`, Python caches, `optidx-theme-icons-*`, virtual
environments, machine-specific configuration, profiles, download caches or prepared
weights as repository source. `.gitignore` excludes the local generated files.
Git ignore rules only affect Git; manually uploading a folder does not apply them.

## Upload through the browser

1. Create a new Desktop repository on GitHub.
2. Use **Add file → Upload files** and upload the **contents of the clean source
   folder**, including `.gitignore`, rather than the whole working directory.
3. Keep folders such as `optidx_desktop/` and `backend/` at the repository root,
   alongside `README.md`. Do not add an extra enclosing source-folder level.
4. Review the file list and create the initial commit.

Uploading a `.tar.gz` alone stores an archive; GitHub does not unpack it into a
source tree. Extract it first if you are using the browser uploader. For repeated
development, use Git instead of browser uploads.

## Upload with Git

Create an empty GitHub repository without generating a README, license or
gitignore, because those files are already present locally. From the clean source
folder:

```bash
git init -b main
git add .
git status --short
git commit -m "Initial public source release"
git remote add origin PASTE_YOUR_NEW_DESKTOP_REPOSITORY_URL_HERE
git remote -v
git push -u origin main
```

Replace `PASTE_YOUR_NEW_DESKTOP_REPOSITORY_URL_HERE` with the URL copied from the
**new Desktop repository**, not the original script repository. GitHub
authentication must already be configured. Review `git status` before committing.

If using the existing working checkout instead of a fresh export, it already has
a Git repository. Skip `git init`; inspect its remotes before adding an `origin`.

## Upload the application separately

Attach these files as assets of a GitHub **Release** in the Desktop repository:

```text
OptiDX-Desktop-0.3.4-x86_64.AppImage
OptiDX-Desktop-0.3.4-x86_64.AppImage.sha256
```

Keep executable builds out of the source commit. A clean source archive can also
be attached to a release, but it does not replace publishing the source tree.
Keep the filename/version examples synchronized with the version being released.

This guide does not create repositories, commit, push, tag or publish anything.

## GitHub references

- [Adding locally hosted code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
- [Uploading existing files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
