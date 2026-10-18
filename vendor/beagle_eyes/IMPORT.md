# Beagle Eyes upstream import

Source: https://github.com/sangregoriokimpo/beagle_eyes
Branch: main
Commit: 7af438bc2294fad090e7329a53a40eb2791d9a41
Commit message: feat: tested on drone

Verified against the remote main head on October 17, 2026. This was the only published branch at inspection time.

Imported upstream scripts, configuration, README, submodule declaration, and DPVO checkpoint byte-for-byte. Excluded committed Python caches and the platform-specific prebuilt MediaMTX binary. Install MediaMTX for the actual host using the cloud deployment instead.

Upstream declares Deep-Visual-Odometry-SLAM as a Git submodule pinned to `f2431991c26f22308b6aed268ca897ad76039409`. Its contents are not included in this source snapshot. The nested `.gitmodules` is provenance, not a registered submodule in our parent repository. Obtain that dependency separately from https://github.com/chansoopark98/Deep-Visual-Odometry-SLAM and check out the pinned commit before inference.

Upstream scripts assume `~/beagle_eyes` paths and a working DPVO/PyTorch environment. They are not immediately runnable from this nested import without adapting paths/dependencies. `setup_uav_rtmp.sh` changes Linux network settings; do not run it on the cloud VM. The cloud stack handles relay networking separately.

The generated image/JSON integration is included as `scripts/uav_vo_firesight.py` with its `frame_bridge.py` helper. Run that script in the configured Beagle environment instead of `uav_vo.py`. The original upstream script remains unchanged.

To regenerate in a fresh upstream checkout, run from our repo root:

```sh
python3 scripts/prepare_beagle_integration.py /path/to/fresh/beagle_eyes
```

This import alone does not deploy or test DPVO on a VM or QNX. No glasses-app branch files were imported.
