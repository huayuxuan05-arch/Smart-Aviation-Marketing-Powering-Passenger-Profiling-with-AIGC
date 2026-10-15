# 航旅主题图

- 文件：`航旅智策应用/web/assets/aviation-coast-hero.png`
- 制作日期：2026-10-15。
- 制作方式：内置 `imagegen` 工具；由本次用户选择的“精品航旅：大幅主题图、深蓝与青绿”方向生成。
- 用途：首页主视觉。个人端与营销端使用下文的独立背景。

- 内容为原创航旅氛围画面，不是具体城市、真实航线或航空公司实拍。首页 alt 文本标明“航旅主题创作”。
- 原图保留；项目使用本地副本，不依赖外部图片地址、API 或字体服务。页面文字、按钮和实时票价均由应用独立渲染，未烘焙进图片。

## 生成提示词

```text
Use case: photorealistic-natural. Asset type: panoramic hero background for a premium Chinese aviation and travel planning website. Create an original editorial travel atmosphere photograph, not a UI mockup. Wide landscape composition, around 16:9. View from the air: a graceful unbranded passenger-aircraft wing enters from the far right edge and points toward the center, gliding above an intricate emerald-green island coastline and a deep teal sea. Beautiful layered clouds and pale warm morning light at the horizon. Restrained natural color, rich deep blue-green shadows, fine realistic detail, premium travel-magazine art direction, quietly inspiring rather than flashy. Composition: the right half carries the wing, islands, and visual interest; the upper-left third is relatively calm muted blue sky with room for website typography to be overlaid separately. The scene should feel expansive and luxurious but plausible. No text, no logos, no watermarks, no airplanes with airline livery, no people, no dashboard graphics, no invented city landmarks. Do not bake any typography or interface into the image.
```

# 独立背景与简化品牌图标

制作日期：2026-10-15；制作方式：内置 `imagegen`，原始输出保留，网站引用项目内的本地副本。

| 资产 | 保存位置 | 用途 |
| --- | --- | --- |
| 晨雾湖山 | `航旅智策应用/web/assets/personal-lake-background.png` | 个人旅客页标题横幅 |
| 晨光浅色机场 | `航旅智策应用/web/assets/marketing-airport-background.png` | 营销人员页面整体背景 |
| 简化品牌 | `航旅智策应用/web/assets/huayi-chaoyang-logo-mountain-wave-v5.png` | 三个入口、网站图标与问卷 |

背景为生成的氛围创作，不标识实际目的地、机场、航空公司或实时业务事实。个人背景延伸至标题区域，营销背景铺在整体页面底部；页面文字与票价仍由应用渲染。首页继续使用机翼海岸图。

最终图标按用户指定的参考版本保留山形字母 A、飞机和环带，移除旅客及行李箱，两道青绿、薄荷色的简洁波浪穿过山形字母的底部，与山脚交叉融合，并调整整体比例与留白。左下白色尖尾完全移除，由青绿波浪直接向左延伸承接山脚。两道波浪保持相同起伏、长度、粗细及间距，端点对齐，山形右下底边沿上方青绿波浪等距平行。深蓝配色与外侧透明边角延续参考图。原品牌 PNG 与生成原图保留，网站与问卷引用新版，历史物料不改写。最终提示词见下文。

## 个人旅客背景提示词

```text
Use case: photorealistic-natural. Asset type: wide panoramic background for the PERSONAL TRAVEL PLANNER page of a premium Chinese aviation and travel website. Create original editorial travel atmosphere imagery, not a website mockup. A serene blue-green alpine lake nestled between layered forested mountain ridges, thin morning mist floating over the water, soft clear dawn light, a subtle distant shoreline path with no people. Calm, restorative and spacious; refined magazine photography, realistic fine texture and restrained natural color. Palette: deep blue-teal water, muted jade-green forest, pale blue-grey mist, gentle warm highlights. Composition for a shallow website banner: panoramic landscape around 16:9; the strongest landscape detail sits on the RIGHT half and the middle horizontal band; the LEFT third stays calm, dark and low-detail, with room to overlay a white page title separately. Keep the horizon around the upper third. No aircraft wings, no ocean coastline, no busy city, no text, no logos, no watermark, no UI, no invented recognizable landmark. Do not bake any interface or typography into the picture.
```

## 营销人员背景提示词（浅色晨光版）

2026-10-15根据用户要求，使用内置 imagegen 重新生成并替换原机场夜景，保存为项目内 PNG。画面采用原生晨光、浅蓝天空与暖白航站楼，页面仅叠加轻薄暖白遮罩和3px虚化。

SHA256：`a29f6c3b9584bbdfe94fbf0c41603f83efac3eb2ef506eb47fc4d68431e1d1f0`

```text
Use case: photorealistic-natural.
Asset type: original wide 16:9 photographic background for a Chinese aviation decision workspace; an image asset only, NOT a website mockup.
Primary request: a naturally LIGHT-COLORED airport scene that harmonizes with warm-white and pale sage content panels.
Scene: a contemporary generic airport apron in gentle early-morning daylight, clean ivory glass-and-steel terminal extending from the right side into the distance, one or two small unbranded passenger aircraft at the right-hand gates. Restrained elegant architectural editorial photography.
Composition: panoramic landscape, high and open pale mist-blue sky across the upper half; the left half remains calm, airy and low detail for dark-blue headings rendered separately by the website. Terminal and aircraft silhouettes occupy the right half and lower-right third. Shallow atmospheric perspective with soft fine details, natural spaciousness. Place no dominant aircraft nose or object in the center.
Lighting: diffuse morning light, soft warm sun filtered through thin clouds, very gentle shadows, light blue-gray apron with subtle reflections. Naturally luminous materials, not a dark scene covered with a white filter. Very slight atmospheric softness, with recognizable airport forms.
Palette: warm ivory, pale cool blue, light sage-gray, a restrained touch of muted teal glass. No deep navy sky, no nighttime lighting, no orange sunset, no hard black shadows. Subdued contrast appropriate behind an information interface.
Constraints: no people in foreground, crowds, airline or airport logos, identifiable landmarks, readable signage, text, numbers, branding, watermarks, UI elements, panels, charts or typography. Original plausible architecture and aircraft, realistic proportions. This is an ambient airport backdrop, not a promise of any real airport or airline. Output one finished image.
```

## 山水融合基础版本提示词

```text
Use case: precise-object-edit / logo-brand. Refine this exact aviation logo to INTEGRATE the mountain-shaped A and the waves into ONE balanced unified emblem. The user's correction is that the current waves float separately below the mountain; instead they must INTERSECT AND INTERWEAVE with the LOWER PART OF THE MOUNTAIN A. Redraw the two simple teal/mint wave strokes across the mountain BASE, with their curves passing through and overlapping the lower mountain slopes/legs. Let the lower mountain legs visually flow into or be cleanly cut by the wave curves, like a mountain rising directly from water. Use clean negative-space separation at crossings, so the mountain A remains recognizable. No disconnected stack of waves beneath a gap. Avoid tangled intersections: the main orbital ring remains a distinct single upward diagonal sweep at the middle, while the new water waves belong only at the lower mountain base. Adjust the mountain and wave proportions together so the COMPLETE MARK has harmonious scale, visually centered mass and generous even padding in the navy rounded-square tile. Mountain remains dominant, plane upper right remains secondary; the integrated mountain/water structure should look compact and coherent, not a tall letter plus underlines. Use exactly two restrained wave curves, teal and pale mint, not a detailed sea illustration. Preserve the original mountain/A identity, white airplane, teal orbital ring, navy background and transparent outside corners. Preserve the existing navy, white, teal and mint palette. Clean simple geometric graphic, crisp silhouette, no extra embellishments. NO traveler, NO suitcase, NO human, NO words or watermark, no UI mockup. Output one finished balanced icon with the mountain and waves visibly fused through clean crossings at the mountain base.
```

## 去除白色尖尾与延伸波浪提示词

内置 `imagegen` 编辑山水融合版本，去掉左下整段白色尖尾，青绿波浪直接向左延伸；原图保留。

```text
Use case: precise-object-edit. Edit this exact logo. The user now explicitly wants the WHITE LOWER-LEFT TAIL REMOVED ENTIRELY and the WAVE extended in its place. Identify the small white curved triangular shard / leaf-shaped mountain foot below the teal diagonal orbital ring and above the left water-wave crest. DELETE THIS WHOLE WHITE SHARD: no white tail, white sliver, white leaf, pointed white foot, or white remnant may remain in that lower-left region. Continue and extend the existing UPPER TEAL WATER WAVE smoothly toward the left through the former white-foot area, so the wave itself becomes the lower-left continuation of the mountain base. Surrounding negative space is the same navy tile background. Make it one simple uninterrupted teal curve, with matching thickness and a clean smooth taper or rounded endpoint. Keep the lower mint wave as the second parallel water curve, balanced with the extended teal wave. Preserve everything else exactly: upper white/mint mountain-shaped A, white right mountain leg, white airplane, entire diagonal teal orbital ring including its own separate left tip, navy rounded-square tile, transparent outside corners and overall palette and proportions. This is a local edit to the lower-left white mountain foot and its directly adjacent teal wave only. Do not reintroduce a white left foot of any kind. No person, suitcase, text, watermark, new symbols or mockup. Output one finished icon with NO WHITE TAIL BELOW THE LEFT SIDE OF THE ORBIT, only a naturally extended teal wave there.
```

## 平行波浪微调提示词

内置 `imagegen` 编辑上一版，将两道波浪调整为同形、同向、端点对齐的平行曲线；保留旧版。

```text
Use case: precise-object-edit. Refine ONLY the two water-wave strokes along the bottom of this exact logo. User requires the two waves to be STRICTLY PARALLEL. Draw the upper teal wave as one clean smooth gently sinusoidal curve with constant stroke thickness and rounded end caps. The lower mint wave must be an EXACT DUPLICATE OF THAT SAME CURVE translated vertically downward by a constant distance, with the same length, amplitude, phase, stroke thickness and end-cap shapes. They have identical rises and falls at identical horizontal positions, consistent separation from left to right, and exactly aligned left and right endpoints. No convergence, divergence, different amplitudes, different wave phases, tapering or varying thickness. Both strokes run across the same horizontal extent, with a clear consistent navy gap between them. Preserve the mountain-water integration and keep NO white lower-left tail; the upper teal wave remains the lower-left continuation. Preserve absolutely all other elements: mountain-shaped A, white right leg, plane, diagonal orbital ring, navy rounded-square tile and transparent outside corners, palette and overall layout. Do not alter the orbit or mountain summit. No added symbols, text, human, baggage or watermark. Output one finished logo with the two bottom waves visibly exact parallel copies.
```

## 山形右下底边与波浪等距平行（当前版本）

内置 `imagegen` 以平行双波浪版为参照，只调整山形右下底边，统一其与青绿波浪之间的留白。

```text
Use case: precise-object-edit. Make ONE precise local adjustment to this logo: the curved BOTTOM EDGE OF THE WHITE LOWER-RIGHT MOUNTAIN LEG must run PARALLEL AND EQUIDISTANT to the TOP EDGE OF THE UPPER TEAL WATER WAVE immediately below it. Treat the teal wave as the fixed master curve. Recut the bottom contour of the white right mountain foot as the same wave curve offset upward by a constant small navy clearance, maintaining visibly uniform navy negative-space width across the ENTIRE shared span of the white foot and teal wave. Neither end may pinch, flare, dip, or form a pointed spur toward the wave. Smoothly finish both ends of this recut white contour into the existing sloping sides of the mountain leg. Adjust only the white foot's lower edge, preserving the main mountain leg silhouette above. Keep the upper teal and lower mint water waves EXACTLY AS THEY ARE: their identical parallel curve profiles, constant gap, aligned endpoints and thickness must remain untouched. Preserve ALL other artwork: the large mountain/A summit and mint slope, white airplane, entire diagonal teal orbital ring, removed lower-left white tail (do not bring it back), navy rounded-square tile, transparent exterior corners, palette, layout and proportions. The visual result should show clean parallel rhythm: white mountain-foot underside, navy gap of uniform width, teal wave, navy gap, mint wave. No people, baggage, words, watermark, mockup or new motifs. Output the finished logo with a consistently spaced parallel interface between the white right mountain base and the teal wave.
```
