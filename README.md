# Cloudflare Random Hitokoto

使用 Cloudflare 规则实现的不限请求次数的随机一言接口。

> 本项目 Fork 并修改自 [Mabbs/cf-hitokoto](https://github.com/Mabbs/cf-hitokoto)，感谢原作者

个人仅作了自动更新与自动生成规则的修改，数据来源与部署方法均与原项目一致。

作者的思路tql，再次依旧感叹天才般的想法。

## 数据来源

[hitokoto-osc/sentences-bundle](https://github.com/hitokoto-osc/sentences-bundle)

## 部署方法

1.  Fork 本仓库。
2.  在 GitHub Settings -> Pages 中启用 Pages，Source 选择 `GitHub Actions`。
3.  配置 Cloudflare 转换规则（Transform Rules -> Rewrite URL）。

### Cloudflare 规则

**全随机重写规则 (Rewrite Path):**
```javascript
concat("/orig_data/", substring(uuidv4(cf.random_seed), 0, 4), ".json")
```
*(注意：`4` 是根据当前数据量自动计算的，请参考生成的 `rules.txt`)*

**带分类重写规则 (Rewrite Path):**
```javascript
concat("/categories/", substring(http.request.uri.query, 2, 3), "/", substring(uuidv4(cf.random_seed), 0, 3), ".json")
```

## API 用法

请求地址：`https://你的域名/`

| 参数 | 值 | 可选 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| **c** | 见 [categories.json](categories.json) | 是 | 句子分类 (单字符) | `?c=a` (动画) |

如果不带参数，则返回全库随机的一言。

### 分类列表 (部分)

*   `a`: 动画
*   `b`: 漫画
*   `c`: 游戏
*   `d`: 文学
*   `e`: 原创
*   `f`: 来自网络
*   `g`: 其他
*   `h`: 影视
*   `i`: 诗词
*   `j`: 网易云
*   `k`: 哲学
*   `l`: 抖机灵

*(完整列表请查看生成的 `categories.json`)*
