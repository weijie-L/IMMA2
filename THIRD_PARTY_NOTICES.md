# 第三方代码与方法声明 / Third-Party Notices

## Met Office MarineQC

本项目的 MDS 航迹检查模块（`imma2_qc/qc/mds_track.py`）改编自
Met Office 的 MarineQC 项目中的 `track_check.py`：

- 项目地址：https://github.com/ET-NCMP/MarineQC
- 方法学文献：Atkinson, C. P., N. A. Rayner, J. Roberts-Jones, and
  R. O. Smith (2013), Assessing the quality of sea surface temperature
  observations from drifting buoys and ships on a platform-by-platform
  basis, *J. Geophys. Res. Oceans*, 118, 3507–3529,
  doi:[10.1002/jgrc.20257](https://doi.org/10.1002/jgrc.20257)

改编内容：多证据组合的航迹检查判定（中点偏差、模态速度上限、
报告航向/航速连续性、外推位置偏差、迭代剔除），并针对 IMMA 数据的
VS/DS 分类码做了适配（详见模块 docstring 中的差异说明）。

MarineQC 以 BSD-3-Clause 许可发布，原始许可文本如下：

---

© British Crown Copyright 2018, Met Office.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

---

## GSHHG 海岸线数据（可选使用）

海陆检查与地图底图可选使用 GSHHG 数据集：

- Wessel, P., and W. H. F. Smith (1996), A global, self-consistent,
  hierarchical, high-resolution shoreline database,
  *J. Geophys. Res.*, 101(B4), 8741–8743,
  doi:[10.1029/96JB00104](https://doi.org/10.1029/96JB00104)

## ICOADS 数据集

本软件处理的观测数据来自 ICOADS：

- Freeman, E., et al. (2017), ICOADS Release 3.0: a major update to the
  historical marine climate record, *Int. J. Climatol.*, 37, 2211–2232,
  doi:[10.1002/joc.4775](https://doi.org/10.1002/joc.4775)
