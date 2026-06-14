# autocodabench GPU base image.
#
# Identical in intent to the CPU image, but starts from the Codabench-hosted
# GPU worker image (CUDA runtime, Python 3.10). It adds the same essential
# scientific-Python stack and pinned notebook toolchain; deep-learning
# frameworks (PyTorch, TensorFlow) are intentionally NOT baked in, because the
# right CUDA-matched build is competition-specific — a bundle that needs one
# should declare it and layer it on top of this image. What this image
# guarantees is that the common stack and the starting-kit runner work out of
# the box on a GPU worker.
#
# Build and push with docker/build_and_push.sh. See docker/README.md.
FROM codalab/codalab-legacy:gpu310

LABEL org.opencontainers.image.title="autocodabench-base-gpu"
LABEL org.opencontainers.image.description="Codabench gpu310 worker image plus the autocodabench essential stack."
LABEL org.opencontainers.image.source="https://github.com/ihsaan-ullah/auto-codabench"

COPY autocodabench-base-requirements.txt /tmp/autocodabench-base-requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir -r /tmp/autocodabench-base-requirements.txt \
 && rm -f /tmp/autocodabench-base-requirements.txt

# Fail the build if the notebook toolchain cannot satisfy the runner's exact
# invocation (see the CPU Dockerfile for the rationale): author and run a tiny
# notebook through `jupyter nbconvert --to notebook --execute --inplace`.
RUN python -c "import numpy, pandas, sklearn, scipy, matplotlib, seaborn, PIL; \
print('autocodabench-base-gpu: stack import OK')" \
 && python -c "import json; json.dump({'cells':[{'cell_type':'code','metadata':{},'source':['print(1+1)'],'outputs':[],'execution_count':None}],'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3'},'language_info':{'name':'python'}},'nbformat':4,'nbformat_minor':5}, open('/tmp/smoke.ipynb','w'))" \
 && jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 /tmp/smoke.ipynb \
 && rm -f /tmp/smoke.ipynb \
 && echo "autocodabench-base-gpu: notebook toolchain OK"
