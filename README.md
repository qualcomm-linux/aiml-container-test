## About The Project

This repository hosts a Dockerfile and its dependencies that aims to build a container with TFLite installed to aid in testing Qualcomm platforms. 

[![Build][build-badge]][build] [![Daily LAVA][daily-badge]][daily]

### How to build

This isn't using any fancy features, so a regular build command will work:

```bash
docker build  --platform linux/arm64 .
```

## How to use the container

Start the container with `host` networking and forwarding the GPU devices nodes inside `/dev/dri`:

```bash
docker run --network host --device /dev/dri -it --entrypoint /bin/bash <container URI>
```

Once inside run the helper script:

```bash
root@qrb2210-rb1-core-kit:/# ./run-tflite.sh
...
LAVA_RESULT test_case_id=tflite-label-image-cpu result=pass measurement=31.488 units=ms
...
LAVA_RESULT test_case_id=tflite-benchmark-mobilenet-quant-v1-224-cpu result=pass measurement=105.784 units=ms
```

Additional `.tflite` models mounted under `/root/models` are benchmarked
recursively. The model directory can remain read-only because benchmark results
are emitted on standard output instead of being written next to the models.

## CI performance results

LAVA records each TensorFlow Lite latency as a native measurement. The workflow
summary renders one Mermaid graph per board, with every measured test shown as
an adjacent bar and an exact-value table below it. Missing accelerators remain
absent rather than being plotted as zero.

Each run uploads a `tflite-performance-<suite>-<boards>` artifact containing
`results.json`, `results.csv`, `raw-logs/`, and `summary.md`. Keying the artifact
by its exact board set keeps targeted runs from displacing another board's
baseline. The report includes the qcom-deb-images input, kernel, TensorFlow Lite
revision, QAIRT version, container digest, AIML commit, and LAVA job/device.
Compatible measurements from the previous report on the same branch are shown
as informational changes.

## License

*AIML container test* is licensed under the [BSD-3-clause License](https://spdx.org/licenses/BSD-3-Clause.html). See [LICENSE](LICENSE) for the full license text.

[build]: https://github.com/qualcomm-linux/aiml-container-test/actions/workflows/build-on-push.yml
[build-badge]: https://img.shields.io/github/actions/workflow/status/qualcomm-linux/aiml-container-test/build-on-push.yml?label=build
[daily]: https://github.com/qualcomm-linux/aiml-container-test/actions/workflows/build-daily.yml
[daily-badge]: https://img.shields.io/github/actions/workflow/status/qualcomm-linux/aiml-container-test/build-daily.yml?label=daily%20LAVA
