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
LAVA_RESULT test_case_id=tflite-label-image-cpu measurement=31.488 units=ms result=pass record_end=1
...
LAVA_RESULT test_case_id=tflite-benchmark-mobilenet-quant-v1-224-cpu measurement=105.784 units=ms result=pass record_end=1
```

Additional `.tflite` models mounted under `/root/models` are benchmarked
recursively. The model directory can remain read-only because benchmark results
are emitted on standard output instead of being written next to the models.
Each logical case runs one unmeasured outer warm-up followed by 10 measured
executions. The published LAVA measurement is the arithmetic mean after
discarding exactly one lowest and one highest sample; raw samples, dispersion
statistics, benchmark-internal statistics, and available read-only DUT telemetry
are retained in the performance artifact.

`benchmark_model` defaults to 10 warm-up runs (at least 1 second) and 100
measured runs (at least 3 seconds, at most 150 seconds) per outer execution.
`label_image` uses its supported `--warmup_runs=10` and `--count=100` options.
These settings can be overridden with the corresponding
`BENCHMARK_*` and `LABEL_IMAGE_*` environment variables; invalid or incomplete
measurements fail the logical test instead of being omitted from the aggregate.

`./benchmark-tflite.sh` runs only the externally mounted models, on CPU and GPU,
using the same validation, timeout, measurement, and result protocol as
`run-tflite.sh`. It fails during preflight if the model directory or requested
GPU device is unavailable.

## Performance tracking

CI tracks TensorFlow Lite latency per board in LAVA. Measurements and comparisons
are published with each [Daily LAVA workflow][daily] run.
LAVA image resolution accepts only successful trusted `qcom-deb-images` workflow
runs from `main` that are no more than 14 days old; all artifact pointer and image
validation remains mandatory.

## License

*AIML container test* is licensed under the [BSD-3-clause License](https://spdx.org/licenses/BSD-3-Clause.html). See [LICENSE](LICENSE) for the full license text.

[build]: https://github.com/qualcomm-linux/aiml-container-test/actions/workflows/build-on-push.yml
[build-badge]: https://img.shields.io/github/actions/workflow/status/qualcomm-linux/aiml-container-test/build-on-push.yml?label=build
[daily]: https://github.com/qualcomm-linux/aiml-container-test/actions/workflows/build-daily.yml
[daily-badge]: https://img.shields.io/github/actions/workflow/status/qualcomm-linux/aiml-container-test/build-daily.yml?label=daily%20LAVA
