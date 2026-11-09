# plaud-health 交接说明（给 OpenCode / 接手的人，2026-11-09）

> 打开这个仓库先读完本文件再动手。

## 一句话
「Plaud 公司健康度看板」：四个「真」指标（出货激活率、订阅转化率、DAU/MAU、NPS）+ 综合健康度分，出货 cohort 视角。
网页：<https://mililiu-cloud.github.io/plaud-health/>（GitHub Pages，仓库**公开**，页面内容加密，打开要输访问口令）。

**⚠ 目前全部是模拟数据**（Mili 2026-11-09 定）：真实数据源还没接，页面顶部黄框写明「模拟数据，请勿引用」。不要把模拟数字当真实数字汇报给任何人。

## 分支
**代码、workflow、网页都在 main**（GitHub Pages 直接发布 main 根目录的 `index.html`）。

## 任务
| 任务（workflow） | 时间 | 产出 |
|---|---|---|
| **健康度看板刷新**（`build.yml` → `tools/build.py`） | **只手动**（没有定时，不在 cron-job.org 清单里；模拟数据没必要定时刷） | 重新生成模拟数据（截至北京时间昨天）→ 用口令加密 → 覆盖 `index.html` 和 `data/health_data.json` 并推到 main，约 1 分钟后网页更新 |

### 手动运行 / 试跑
```bash
R=mililiu-cloud/plaud-health
gh workflow run build.yml -R $R -f dry=true                    # 试跑：只生成不发布
gh workflow run build.yml -R $R -f dry=false                   # 正式刷新网页
gh workflow run build.yml -R $R -f dry=false -f asof=2026-11-30  # 指定「数据截至」日期
gh run watch -R $R
```
本地看效果（不需要口令、不改网页，预览文件**不要提交**）：
```bash
python3 tools/build.py --preview /tmp/health_preview.html && open /tmp/health_preview.html
```
本地要生成加密版需要 `pip install cryptography`，并设环境变量 `HEALTH_PAGE_PASSWORD`（口令问 Mili，**不要让她贴进聊天**；一般直接用上面的 workflow 就行）。

## 文件
| 文件 | 作用 |
|---|---|
| `tools/build.py` | 生成脚本：`make_data()` 造模拟数据 → `render()` 出页面 → `encrypt()` 加密 → 套进口令页写 `index.html` |
| `tools/login_shell.html` | 口令页模板（`__PAYLOAD__` 处放加密内容）。解密：PBKDF2-SHA256 25 万次 + AES-256-GCM，和 `encrypt()` 对应，**两边要一起改** |
| `data/health_data.json` | 页面用的全部数字（模拟），自动生成，不要手改 |
| `index.html` | 发布的网页（自动生成，不要手改） |

## 指标口径（页面「口径与数据源」一节也有）
- **出货 cohort**：按出货月份分批（计划用易仓「仓库发货时间」），每批看出货后 30/60/90 天。出货月最后一天 + N 天还没到的批次显示「—」。
- **出货激活率 (T+90)** = 批内 90 天内激活台数 ÷ 批内出货台数。权重 30%，归一化区间 40→90，预警/健康线 60/75。
- **订阅转化率 (T+90)** = 批内 90 天内开通付费订阅人数 ÷ 批内出货台数。权重 25%，5→30，12/20。
- **DAU/MAU** = 当月日活日均 ÷ 当月月活（按自然月，只算过完的月）。权重 25%，10→35，15/25。
- **NPS** = 推荐者% − 贬损者%。权重 20%，−20→80，30/50。
- **综合健康度** = 各项按归一化区间线性折成 0–100 分后加权；≥75 健康、50–75 需关注、<50 预警。
- 「较上一完整期」：激活/订阅比上一个出货月，DAU/MAU、NPS 比上一个自然月。
- 区域：美洲 / 欧洲中东非 / 亚太 / 中国。
- 这些权重和阈值是旧版看板（2026-08，在 Claude 里做的）定的，改口径要先问 Mili。

## 模拟数据怎么来的
`make_data()` 对每个「出货月 × 区域」用固定种子生成：同一个月重跑数字不变，日期往后推只会多出新月份、或让没满天数的批次变成可算。

## 以后接真实数据（还没做）
只要把 `make_data()` 换成读真实来源、输出同样结构的 dict（见 `data/health_data.json`），页面部分不用改。接好后去掉页面黄框和页脚的「模拟数据」字样。
| 部分 | 来源 | 状态 |
|---|---|---|
| 出货量（分母） | 易仓订单接口 `getOrderList`（物流看板 Logistics-OKR-Dashboard 的 `OKR/fetch_live_lastmile.py` 里有现成的调用；钥匙在 Claims-Monitor 私有仓库 `万邑通-订单监控/eccang_config.json`） | 可接，未接 |
| 激活 / 订阅 / DAU·MAU | 软件 / 数据团队（data-portal 或 Snowflake），需要按出货月汇总，最好能按 SN 或订单号对上 | 没有来源 |
| NPS | 用户调研 | 没有来源 |

**仓库是公开的**：接真实数据时，钥匙一律放 GitHub Secret（或在 workflow 里 clone 私有仓库读），**明细数据不要提交进本仓库**（`data/health_data.json` 只能放汇总数字；不能有客户姓名、邮箱、电话、地址）。需要跑接口的话建议把取数放到私有仓库，只把汇总结果推过来。

## 钥匙（只写名字，不写值）
| 用途 | 位置 |
|---|---|
| 网页访问口令 | Secret **`HEALTH_PAGE_PASSWORD`**（Mili 自己放的；换口令 = 改这个 Secret 再手动刷新一次） |

---

## 通用规则（所有仓库都一样）
- 用**中文**、说人话：Mili 是物流负责人，不是程序员。先给结论，短。
- 改动前先用一两句话说清楚「要改什么、会影响什么」；涉及**业务口径**（怎么算、阈值、权重）先问 Mili。
- 钥匙（token、app_secret、密码）**绝不写进代码、提交、聊天或日志**，只用 GitHub Secret。
- **私有仓库保持私有**，不要改公开、不要加协作者；本仓库公开，**不能放客户个人信息**和钥匙。
- 不要 `git push --force`、不要改写历史。
- 开定时之前先问 Mili（GitHub Actions 每月预算 20 美元，能省就省）。
- 提交署名 `Mili <mili.liu@plaud.ai>`，提交说明用中文。
- 做完如实汇报：成功 / 失败（附原始报错）/ 哪一步跳过了。
