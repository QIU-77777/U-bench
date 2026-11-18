你是投研数据库维护助理。当前工作区里已经放好一组合成静态投研资料包：券商摘要 markdown、预测明细 workbook、评级映射 codebook、公司别名字典和输出 schema。请只使用当前工作区提供的静态文件，不运行脚本、不联网、不查询真实行情、不调用券商、交易、邮件、IM 或任何外部接口，不生成投资建议、评级建议、目标价建议、交易动作或消息发送记录。
请读取 `broker_summaries/` 下的摘要文件、`forecast_tables.xlsx`、`rating_codebook.json`、`company_dictionary.xlsx` 和 `output_schema.json`，生成两个文件：`output/analyst_forecast_extract.xlsx` 和 `output/analyst_forecast_extract.json`。
`analyst_forecast_extract.xlsx` 必须包含四个 sheet：`forecast_fields`、`rating_changes`、`target_price_table`、`missing_fields`。
`forecast_fields` 的列依次为 institution、report_date、canonical_company、fiscal_year、net_profit_cny_mn、eps_cny、source_file、source_row_or_section。
`rating_changes` 的列依次为 institution、report_date、canonical_company、source_rating_text、standard_rating、action_type、source_file。
`target_price_table` 的列依次为 institution、report_date、canonical_company、target_price_cny_per_share、target_price_status、source_file。
`missing_fields` 的列依次为 institution、report_date、company_alias、missing_type、evidence、source_file。
关键口径以 `output_schema.json` 为准：目标公司和别名必须用 `company_dictionary.xlsx` 的 active alias 归一；评级标准化必须使用 `rating_codebook.json`，不得自由解释 codebook 外的情绪词；报告日期统一为 `YYYY-MM-DD`；预测年度统一为四位 fiscal year；归母净利润单位统一为 CNY_mn，EPS 单位为 CNY；目标价单位统一为 CNY/share。缺失目标价、缺失预测数值、非目标公司行、滚动统计摘要这类不能进入主事实表的记录，按 schema 写入 `missing_fields`，不要补猜缺失值。滚动汇总、同业统计、页面 footer、免责声明和资料下载入口不是单条机构报告，不得作为 forecast 或 rating 事实输出。
`analyst_forecast_extract.json` 必须包含 `case_id`、`workbook`、`target_company`、`sheet_row_counts` 和 `normalization_contract`，用于下游导入核对。

请读取工作区中的输入文件：`input/broker_summaries/summary_chenqiao_sec_2026-03-18.md`、`input/broker_summaries/summary_beiling_research_2026-03-19.md`、`input/broker_summaries/summary_cedar_capital_2026-03-21.md`、`input/broker_summaries/summary_donggang_sec_2026-03-23.md`、`input/broker_summaries/summary_feisun_markets_2026-03-25.md`、`input/broker_summaries/summary_guankou_sec_2026-03-26.md`、`input/broker_summaries/summary_rollup_statistics_2026-03-27.md`、`input/forecast_tables.xlsx`、`input/rating_codebook.json`、`input/company_dictionary.xlsx`、`input/output_schema.json`。
