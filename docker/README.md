# autocodabench base images

This directory defines two base container images that autocodabench uses as
the default `docker_image` for generated competition bundles:

| Image | From | For |
|---|---|---|
| `autocodabench-base-cpu` | `codalab/codalab-legacy:py312` | CPU bundles (the common case) |
| `autocodabench-base-gpu` | `codalab/codalab-legacy:gpu310` | bundles whose plan requires a GPU |

Both start from the Codabench-hosted worker images, so a program that runs in
them runs the same way on the platform, and both pre-install the essential
scientific-Python stack plus a pinned starting-kit notebook toolchain
(`docker/autocodabench-base-requirements.txt`).

## Why these exist

Codabench's worker executes a bundle's programs *inside* its declared
`docker_image` and never installs `requirements.txt`. Two recurring failure
modes follow from that, and both are addressed by baking dependencies into a
base image rather than discovering them per run:

1. **Stale libraries in legacy images.** `codalab/codalab-legacy:py3` ships
   scikit-learn 0.19.1, which predates symbols a modern bundle uses (for
   example `balanced_accuracy_score`). Building on a current interpreter
   (Python 3.12 / 3.10) with the current stack removes this class of error.
2. **Notebook-toolchain incompatibility.** The starting-kit runner executes
   the notebook with `jupyter nbconvert --to notebook --execute --inplace`
   (nbconvert stops nonzero on the first cell error and writes outputs back).
   nbconvert 7.x drives nbclient under the hood; the requirements file pins
   nbclient to the 0.7 line to keep that pairing on a known-good combination,
   and each image's build runs a tiny notebook through this exact command so a
   broken toolchain fails the build rather than surfacing at run time.

Pre-installing this stack also means most bundles execute with **no per-run
installation at all**, which conserves the operator's model budget — the build
agent no longer spends turns resolving dependencies that the image already
provides.

## Build and push

```bash
# Build both images locally under your namespace (default: "autocodabench"):
docker/build_and_push.sh <namespace> <tag>

# Build and push (requires `docker login`):
docker/build_and_push.sh <namespace> <tag> --push

# Examples:
docker/build_and_push.sh myhubuser latest --push
AUTOCODABENCH_DOCKER_NAMESPACE=myhubuser docker/build_and_push.sh
```

This produces and (optionally) pushes:

```
<namespace>/autocodabench-base-cpu:<tag>
<namespace>/autocodabench-base-gpu:<tag>
```

## Make them the runner defaults

autocodabench resolves the default image from environment variables, falling
back to the `autocodabench` namespace:

```bash
export AUTOCODABENCH_DOCKER_NAMESPACE=myhubuser           # rewrite just the namespace, or…
export AUTOCODABENCH_DOCKER_IMAGE=myhubuser/autocodabench-base-cpu:latest
export AUTOCODABENCH_DOCKER_IMAGE_GPU=myhubuser/autocodabench-base-gpu:latest
```

The build agent writes the chosen image into each bundle's
`competition.yaml`, and — if the self-validation loop has to change it to get a
passing run — records the *final, working* image there. Until you have built
and pushed these images, point `AUTOCODABENCH_DOCKER_IMAGE` at a stock image
that ships the dependencies (for example `codalab/codalab-legacy:py312`).

## Architecture and Apple silicon

`create` and `validate` open with a Docker preflight that reports the
image's CPU architecture against the host. An image whose architecture does not
match the host still runs, but under QEMU emulation — correct yet slow.

- The Codabench CPU base, `codalab/codalab-legacy:py312`, is **multi-arch**
  (amd64 **and** arm64). Built locally on an Apple-silicon Mac, the
  autocodabench CPU image is therefore native arm64 and runs without emulation.
- The GPU base, `codalab/codalab-legacy:gpu310`, is **amd64-only** (and targets
  CUDA), so on a Mac it builds and runs under emulation and cannot use a GPU.
  Build it on a Linux/GPU host; for local CPU development, build only the CPU
  image:

  ```bash
  docker build -f docker/autocodabench-cpu.Dockerfile \
    -t autocodabench/autocodabench-base-cpu:latest docker/
  ```

For quick local testing without building anything, point the runner at the
stock multi-arch CPU base (Docker resolves the host architecture for you):

```bash
export AUTOCODABENCH_DOCKER_IMAGE=codalab/codalab-legacy:py312
```

## Adjusting the stack

Edit `autocodabench-base-requirements.txt` (the single source of truth for
both images) and rebuild. The core data-science packages are intentionally
unpinned so each image tracks the latest release compatible with its
interpreter; the notebook toolchain is pinned and should be changed only
together with the runner's notebook invocation.
