# 队名映射表

中文队名 ↔ 英文队名 ↔ FIFA TLA 三字母码。用于跨数据源匹配。

## 格式

```
中文名 | English Name | TLA
```

## 世界杯 2026 参赛队

### Group A
```
墨西哥     | Mexico              | MEX
韩国       | South Korea         | KOR
捷克       | Czech Republic      | CZE
南非       | South Africa        | RSA
```

### Group B
```
瑞士       | Switzerland         | SUI
加拿大     | Canada              | CAN
卡塔尔     | Qatar               | QAT
波黑       | Bosnia & Herzegovina| BIH
```

### Group C
```
巴西       | Brazil              | BRA
摩洛哥     | Morocco             | MAR
苏格兰     | Scotland            | SCO
海地       | Haiti               | HAI
```

### Group D
```
美国       | USA                 | USA
土耳其     | Turkey              | TUR
澳大利亚   | Australia           | AUS
巴拉圭     | Paraguay            | PAR
```

### Group E
```
德国       | Germany             | GER
厄瓜多尔   | Ecuador             | ECU
科特迪瓦   | Ivory Coast         | CIV
库拉索     | Curacao             | CUW
```

### Group F
```
荷兰       | Netherlands         | NED
瑞典       | Sweden              | SWE
日本       | Japan               | JPN
突尼斯     | Tunisia             | TUN
```

### Group G
```
比利时     | Belgium             | BEL
埃及       | Egypt               | EGY
伊朗       | Iran                | IRN
新西兰     | New Zealand         | NZL
```

### Group H
```
西班牙     | Spain               | ESP
乌拉圭     | Uruguay             | URY
沙特阿拉伯 | Saudi Arabia        | KSA
佛得角     | Cape Verde          | CPV
```

### Group I
```
法国       | France              | FRA
挪威       | Norway              | NOR
塞内加尔   | Senegal             | SEN
伊拉克     | Iraq                | IRQ
```

### Group J
```
阿根廷     | Argentina           | ARG
奥地利     | Austria             | AUT
阿尔及利亚 | Algeria             | ALG
约旦       | Jordan              | JOR
```

### Group K
```
葡萄牙     | Portugal            | POR
哥伦比亚   | Colombia            | COL
刚果(金)   | DR Congo            | COD
乌兹别克斯坦| Uzbekistan         | UZB
```

### Group L
```
英格兰     | England             | ENG
克罗地亚   | Croatia             | CRO
加纳       | Ghana               | GHA
巴拿马     | Panama              | PAN
```

## 五大联赛

详见 `data/features_*2024.csv` 中的队名。中文名映射见 `scripts/deepseek_predictor.py` 中的 `TEAM_NAME_MAP`。

## 使用说明

- 500.com 返回中文队名 → 通过此表查找 TLA
- OpenFootball 返回英文队名 + FIFA TLA
- football-data.org 返回英文队名 + TLA
- WebSearch 结果中英文混合 → 通过此表统一

## 添加新队伍

1. 在此文件中按组添加映射
2. 在 `scripts/deepseek_predictor.py` 的 `TEAM_NAME_MAP` 中同步
