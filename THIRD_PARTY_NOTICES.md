# Third-party notices

The OBS Bilingüe source code is GPL-2.0-or-later (see `LICENSE`). The installer is
an aggregate of separately licensed components; this does not relicense model
weights, CUDA, Python or other dependencies under the project's GPL license.

| Component | Version / origin | License and bundled notice |
| --- | --- | --- |
| Nemotron 3.5 ASR Streaming 0.6B Q8 | Original NVIDIA weights; pinned revision in `installer/resources.json` | OpenMDW-1.1; `licenses/OpenMDW-1.1.html` and original model card |
| NeMo-Speech.cpp | NVIDIA v0.2.0 official CUDA release | Original licenses, NOTICE and third-party notices in `runtime/nemo/share/licenses` |
| Hy-MT2 1.8B Q4 | Tencent original GGUF; pinned revision | Apache-2.0; `licenses/Hy-MT2-Apache-2.0.txt` |
| llama.cpp | ggml-org b11429 | MIT; `licenses/llama.cpp-MIT.txt`, accompanying LLVM/OpenMP notice |
| NVIDIA CUDA runtime libraries | Original CUDA release archives above | NVIDIA CUDA EULA; `licenses/CUDA-EULA.html`; no driver is redistributed |
| CPython | 3.12.14, python-build-standalone via uv | Python license and third-party notices accompanying bundled Python |
| Silero VAD | v6.2.0 | MIT; `assets/SILERO-LICENSE.txt` |
| Python dependencies | Fully pinned in `requirements-bundle.lock` | Their license files remain in `python/Lib/site-packages` |

Python packages include NumPy, FastAPI, uvicorn, soxr, httpx, psutil, langid,
Lingua, sherpa-onnx, huggingface-hub and their dependencies. Their versions,
package hashes and license notices are retained in the distribution. They are
separate components with their respective upstream terms. Corresponding source
is available from their pinned PyPI source distributions and upstream projects.

The packaged original models are not the rejected experimental adaptations.
No OBS binaries, NVIDIA driver, user audio, transcriptions or private training
data are included. Inno Setup is used to create the installer; see
<https://jrsoftware.org/isinfo.php>.
