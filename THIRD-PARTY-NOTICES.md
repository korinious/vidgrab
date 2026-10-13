# Third-party notices

VidGrab is free software under the **GNU General Public License v3.0 or later**
(`LICENSE`). Its source code: <https://github.com/korinious/vidgrab>.

The Windows zip also contains the programs and libraries below. Each keeps its own
license; the license texts are in the `licenses` folder of the zip (`LICENSES/` in the
repository).

## FFmpeg 8.0 (ffmpeg.exe, ffprobe.exe): GPL-3.0

- Build: "essentials" build `8.0-essentials_build-www.gyan.dev` by gyan.dev,
  <https://www.gyan.dev/ffmpeg/builds/>, downloaded from
  <https://github.com/GyanD/codexffmpeg/releases/tag/8.0> (SHA256 pinned in
  `.github/workflows/build.yml`). It is configured with `--enable-gpl --enable-version3`,
  so the binaries are licensed under the GPL v3.
- Source code: FFmpeg tag `n8.0` (commit
  [140fd653ae](https://github.com/FFmpeg/FFmpeg/commit/140fd653aed8cad774f991ba083e2d01e86420c7)).
  The source tarball `ffmpeg-8.0.tar.xz` is attached to **every VidGrab release**, next to
  the zip, and is also at <https://ffmpeg.org/releases/ffmpeg-8.0.tar.xz>.
- In the zip: `licenses/FFMPEG-LICENSE.txt` (GPL v3), `licenses/FFMPEG-README.txt` (the
  build's README: configuration, libraries and their versions) and
  `licenses/FFMPEG-BUILDCONF.txt` (the output of `ffmpeg -buildconf`).
- VidGrab runs ffmpeg.exe and ffprobe.exe as separate programs; it does not link to them.

### Build configuration (`ffmpeg -buildconf`)

CI checks that these flags match the bundled ffmpeg.exe (`scripts/check_ffmpeg_buildconf.py`).

```text
  configuration:
    --enable-gpl
    --enable-version3
    --enable-static
    --disable-w32threads
    --disable-autodetect
    --enable-fontconfig
    --enable-iconv
    --enable-gnutls
    --enable-libxml2
    --enable-gmp
    --enable-bzlib
    --enable-lzma
    --enable-zlib
    --enable-libsrt
    --enable-libssh
    --enable-libzmq
    --enable-avisynth
    --enable-sdl2
    --enable-libwebp
    --enable-libx264
    --enable-libx265
    --enable-libxvid
    --enable-libaom
    --enable-libopenjpeg
    --enable-libvpx
    --enable-mediafoundation
    --enable-libass
    --enable-libfreetype
    --enable-libfribidi
    --enable-libharfbuzz
    --enable-libvidstab
    --enable-libvmaf
    --enable-libzimg
    --enable-amf
    --enable-cuda-llvm
    --enable-cuvid
    --enable-dxva2
    --enable-d3d11va
    --enable-d3d12va
    --enable-ffnvcodec
    --enable-libvpl
    --enable-nvdec
    --enable-nvenc
    --enable-vaapi
    --enable-openal
    --enable-libgme
    --enable-libopenmpt
    --enable-libopencore-amrwb
    --enable-libmp3lame
    --enable-libtheora
    --enable-libvo-amrwbenc
    --enable-libgsm
    --enable-libopencore-amrnb
    --enable-libopus
    --enable-libspeex
    --enable-libvorbis
    --enable-librubberband
```

### GPL libraries in this build

| Library | Version in the build | License | Source |
| --- | --- | --- | --- |
| x264 | 0.165.3222 | GPL-2.0-or-later | <https://code.videolan.org/videolan/x264> |
| x265 | 4.1-191-g8f11c33ac | GPL-2.0-or-later | <https://bitbucket.org/multicoreware/x265_git> |
| Xvid (xvidcore) | 1.3.7 | GPL-2.0-or-later | <https://labs.xvid.com/source/> |
| vid.stab | 1.1.1-18-gd9933c1 | GPL-2.0-or-later | <https://github.com/georgmartius/vid.stab> |
| Rubber Band | 1.8.1 | GPL-2.0-or-later | <https://github.com/breakfastquay/rubberband> |
| AviSynth+ (headers; loaded at run time if installed) | 3.7.5-26-g7ae5d480 | GPL-2.0-or-later with linking exception | <https://github.com/AviSynth/AviSynthPlus> |

### Other libraries in this build

Versions as listed in the build's README; each project's license applies.

| Library | Version | Source |
| --- | --- | --- |
| AMF | 1.4.36-3-gcf4445f | <https://github.com/GPUOpen-LibrariesAndSDKs/AMF> |
| aom (AV1) | 3.12.1-256-g1e5fd6abb3 | <https://aomedia.googlesource.com/aom> |
| ffnvcodec | 13.0.19.0-1-gf2fb9b3 | <https://github.com/FFmpeg/nv-codec-headers> |
| FreeType | 2.13.3 | <https://gitlab.freedesktop.org/freetype/freetype> |
| FriBidi | 1.0.16-2-gb28f43b | <https://github.com/fribidi/fribidi> |
| GSM | 1.0.22 | <https://www.quut.com/gsm/> |
| HarfBuzz | 11.4.1-19-gc6153c73 | <https://github.com/harfbuzz/harfbuzz> |
| LAME | 3.100 | <https://lame.sourceforge.io/> |
| libass | 0.17.4-15-g534a5f8 | <https://github.com/libass/libass> |
| Game_Music_Emu (libgme) | 0.6.4 | <https://github.com/libgme/game-music-emu> |
| opencore-amr (amrnb, amrwb) | 0.1.6 | <https://sourceforge.net/projects/opencore-amr/> |
| libssh | 0.11.2 | <https://git.libssh.org/projects/libssh.git> |
| Theora | 1.2.0 | <https://gitlab.xiph.org/xiph/theora> |
| libwebp | 1.6.0-55-g8a2b400 | <https://chromium.googlesource.com/webm/libwebp> |
| OpenAL Soft | (latest at build time) | <https://github.com/kcat/openal-soft> |
| libopenmpt | 0.6.24-26-gc9f88bd6b | <https://lib.openmpt.org/libopenmpt/> |
| Opus | 1.5.2-174-g9c779ed8 | <https://gitlab.xiph.org/xiph/opus> |
| SDL | 2.32.0-89-g1f21aae24 | <https://github.com/libsdl-org/SDL> |
| Speex | 1.2.1-51-g0589522 | <https://gitlab.xiph.org/xiph/speex> |
| SRT | 1.5.4-37-g5d80411 | <https://github.com/Haivision/srt> |
| VAAPI | 2.23.0 | <https://github.com/intel/libva> |
| VMAF | 3.0.0-113-g2b2cf9c1 | <https://github.com/Netflix/vmaf> |
| VisualOn AMR-WB encoder | 0.1.3 | <https://sourceforge.net/projects/opencore-amr/> |
| Vorbis | 1.3.7-10-g84c02369 | <https://gitlab.xiph.org/xiph/vorbis> |
| oneVPL / libvpl | 2.15 | <https://github.com/intel/libvpl> |
| libvpx | 1.15.2-100-g40561f514 | <https://chromium.googlesource.com/webm/libvpx> |
| ZeroMQ | 4.3.5 | <https://github.com/zeromq/libzmq> |
| zimg | 3.0.6-208-g1f53009 | <https://github.com/sekrit-twc/zimg> |
| OpenJPEG, libxml2, GnuTLS, GMP, fontconfig, libiconv, bzip2, xz (lzma), zlib | see FFMPEG-README.txt | <https://www.gyan.dev/ffmpeg/builds/> |

## Deno 2.9.6 (deno.exe): MIT

- <https://github.com/denoland/deno/tree/v2.9.6>, official release binary
  `deno-x86_64-pc-windows-msvc.zip` (SHA256 pinned in `build.yml`).
- License: `licenses/deno-MIT.txt`. Deno includes V8 (BSD-3-Clause) and Rust crates
  under their own licenses, see the Deno repository.
- yt-dlp runs deno.exe as a separate program for YouTube's JavaScript challenges.

## Qt for Python (PySide6 6.11.2) and Qt 6: LGPL-3.0

- Used under the LGPL v3: `licenses/qt-pyside6-LGPL-3.0.txt` (with the GPL v3 text in
  `LICENSE.txt`).
- Source: <https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.11.2> and
  <https://download.qt.io/official_releases/qt/6.11/>.
- The zip is a folder build (PyInstaller `--onedir`): the Qt and PySide6 libraries are
  separate DLL/PYD files under `VidGrab\_internal\PySide6\`, so you can replace them with
  your own builds of the same version.

## Python 3.12: PSF License

`licenses/python-PSF.txt`. Source: <https://www.python.org/downloads/source/>.

## Python packages

yt-dlp (Unlicense), yt-dlp-ejs, mutagen (GPL-2.0-or-later), certifi (MPL-2.0; source:
<https://github.com/certifi/python-certifi>), requests, urllib3, websockets, brotli,
pycryptodomex, platformdirs, Send2Trash and their dependencies. The zip has
`licenses/python/INDEX.md` with the exact versions and each package's license files, made
at build time by `scripts/third_party_licenses.py`. Sources: <https://pypi.org/>.

## PyInstaller bootloader: GPL-2.0 with the bootloader exception

The exception allows distributing the bootloader with programs under any license.
<https://github.com/pyinstaller/pyinstaller>.

## Lucide icons: ISC

`licenses/lucide-ISC.txt`, <https://lucide.dev/>.
