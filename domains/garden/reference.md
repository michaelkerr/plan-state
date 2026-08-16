# Garden Rotation & Succession Reference
### Murfreesboro, TN (Zone 7a) · 6 sections · 5+1 rotation · herbs at the patio

Design rules, variety guidance, and agronomic rationale for the garden's
rotation system. This document is the system's constitution: it changes when
the rotation is redesigned, not when something is planted or harvested.

**Current operational state** (what's planted, what's due, section assignments,
rotation position) lives in the plansync DB and is exported daily to the
dossier at `domains/garden/dossier.md`. If this document and the dossier
disagree on operational facts, the dossier is correct.

Supersedes succession-system v1--v3.

---

## 1. Date anchors

| Anchor | Nashville (UT W436) | Murfreesboro (adjusted) | Use for |
|---|---|---|---|
| Last spring frost, 10% risk | Apr 21 | ~Apr 21--24 | Transplants you can't afford to lose |
| Last spring frost, average | ~Apr 10--15 | ~Apr 12--15 | Normal planning |
| First fall frost, average | Oct 28 | **~Oct 23** | Back-counting fall crops |
| First fall frost, 10% risk | Oct 10 | ~Oct 8--10 | Must-harvest-before-cold |

All dates assume avg first frost **Oct 23**. Log your actual dates. After three years your own records beat the table, and you should replace it.

**The garden year runs Sept 1 -- Aug 31.** Garlic and strawberries both start in fall and finish in June. A Jan--Dec year splits both and makes the rotation unreadable.

---

## 2. Yard layout & sections

### Geometry

The yard's long axis runs east-west. The house and patio are at the east end; the back fence is at the west end. North is to the right when facing the back fence from the house.

South Bed runs east-west along the south (left) edge of the yard. North Bed runs east-west along the north (right) edge. Berry Beds A & B run north-south along the back (west) fence, separated by a gate at center. Patio at the east (house) end, centered between the raised beds, directly across from the back fence gate. Pot annex sits in the open yard between the beds, just west of (behind) the patio. Apple trees at the west end of each raised bed, near the back fence.

When rendering a bird's-eye layout: north points right, west (back fence) is at the top, east (house/patio) is at the bottom. Raised beds as vertical strips on left (south) and right (north) edges. Berry beds horizontally across the top. Patio centered at the bottom.

### Raised bed sections

| ID | Location |
|---|---|
| S1 | South bed, west end (under apple) |
| S2 | South bed, middle |
| S3 | South bed, east end |
| N1 | North bed, west end (under apple) |
| N2 | North bed, middle |
| N3 | North bed, east end |

Both beds are continuous at **36 ft = 3 x 12 ft sections**. The north bed was extended Aug 2026: plum/peach tree removed, 6 ft gap between old Bed 2 (18 ft) and old Bed 3 (12 ft) filled. Gap fill: 6 x 3.5 ft x 12 in = 21 cu ft (8.4 topsoil / 10.5 compost / 2.1 sand).

Raised beds are **12 in deep**, filled with the standard mix (40% topsoil / 50% compost / 10% sand) on leveled ground. Native clay sits below but is not the growing medium.

**Root barriers at both apples.** S1 and N1 sit at the drip lines. If they carry the same crops as everything else they need the same water and nitrogen. Cut a 12--18 in vertical trench at each drip line, line it (60-mil pond liner, HDPE root barrier, scrap roofing), backfill. Re-cut every 2--3 years. Without this, two of six sections quietly underperform while the map claims they're equal.

Afternoon shade on those ends is unfixable. Expect S1/N1 to run slightly behind.

### Berry beds (back fence)

| Bed | Length |
|---|---|
| Bed A | 30 ft |
| Bed B | 30 ft |

Pattern per bed, outer end inward: 2 blackberry, 3 raspberry, 3 blueberry, 1 rosemary, 2 thyme. In-ground plantings in amended native clay (not the standard 40/50/10 mix); soil amended per plant at planting time. Blueberries need acidic soil (pH 4.5--5.5); cane fruits need good drainage but not low pH; rosemary and thyme are intolerant of wet feet (extra sand/gravel in the planting hole).

---

## 3. The rotation

**5+1 system.** Five mobile groups rotate through whichever five sections are not occupied by strawberries. Strawberries hold one section for **3 years**, then move to the section vacating Alliums. The vacated strawberry section receives Legumes.

| # | Group | Crops |
|---|---|---|
| 1 | **Legumes -> Brassicas** | Southern peas Jul -> fall brassicas Aug--Dec |
| 2 | **Solanaceae** | Tomato (peppers live in pots -- see Pot Annex) |
| 3 | **Cucurbits** | Summer squash, cucumber, melons |
| 4 | **Roots & chenopods** | Spring carrot, beet, chard |
| 5 | **Alliums** | Garlic (Oct) + onions (Feb), interplanted in alternating rows |
| +1 | **Strawberries** | Certified plugs, 3-year stay, annual renovation |

Each mobile group advances one section per year among the five non-strawberry sections, giving a **5-year return** for mobile groups. Strawberries return to any given section every **18 years** (6 sections x 3 years). Both exceed UT's recommended 4-year minimum.

### The canonical march

The rotation began in garden year 2027 (Sep 2026 -- Aug 2027). Mobile sections
advance one row each January; strawberry sections hold and mark the year count.
The dossier shows the current position; this table is the reference plan.

| Year | S1 | S2 | S3 | N1 | N2 | N3 |
|---|---|---|---|---|---|---|
| **2027** | Straw (1) | Alliums | Solanaceae | Cucurbits | Leg -> Brass | Roots |
| **2028** | Straw (2) | Leg -> Brass | Cucurbits | Roots | Solanaceae | Alliums |
| **2029** | Straw (3) | Solanaceae | Roots | Alliums | Cucurbits | Leg -> Brass |
| **2030** | Leg -> Brass | Cucurbits | Alliums | Straw (1) | Roots | Solanaceae |
| **2031** | Solanaceae | Roots | Leg -> Brass | Straw (2) | Alliums | Cucurbits |
| **2032** | Cucurbits | Alliums | Solanaceae | Straw (3) | Leg -> Brass | Roots |

### What one section sees

**Mobile cycle** (repeats 2--3 times between strawberry stints):

| Yr | Group | Needs ground | Frees | Handoff |
|---|---|---|---|---|
| 1 | Legumes -> Brassicas | Jul 1 | Jan 15 | -> Solanaceae needs Feb 20 |
| 2 | Solanaceae | Feb 20 | Nov 5 | -> Cucurbits needs May 5 |
| 3 | Cucurbits | May 5 | Nov 5 | -> Roots needs Mar 1 |
| 4 | Roots & chenopods | Mar 1 | **Sep 25** | -> **garlic needs Oct 15** |
| 5 | Alliums | **Oct 15** | Sep 1 | -> Straw Sep 20 *or* **Gap C** (303 d) -> Leg Jul 1 |

**Strawberry stint** (every 18 years per section):

| Yr | Group | Needs ground | Frees | Handoff |
|---|---|---|---|---|
| 6 | Strawberries (yr 1) | Sep 20 | -- | renovate; continue |
| 7 | Strawberries (yr 2) | -- | -- | renovate; continue |
| 8 | Strawberries (yr 3) | -- | Jun 10 | -> Legumes Jul 1 |

After Alliums, strawberries intercept every 3rd cycle (19 d gap). The other 2 of 3 times, the section wraps to Legumes via **Gap C** (303 d, Sep 1 -> Jul 1) -- filled with mache + arugula (see Winter Gaps).

### Why this order

**Calendar handoffs pin most of it.** Garlic (Oct 15) and strawberry plugs (Sep 20) both need a predecessor that clears in September. Only Roots-plus-buckwheat and Alliums-plus-buckwheat do, which fixes positions 4 and 5. Strawberries always follow Alliums when they move -- the Sep 1 clear -> Sep 20 plugs handoff constrains this. Strawberries free the ground Jun 10, so their successor can't need it before July, which fixes Legumes at position 1. Legumes hold to January, so position 2 must be a February-or-later starter.

**The nutrient cascade justifies the rest.**

| Yr | Group | Nitrogen | Rooting depth |
|---|---|---|---|
| 1 | Legumes -> Brassicas | Peas fix N; brassicas scavenge residual nitrate that would otherwise leach; residue chopped in Dec releases it over winter | shallow -> medium |
| 2 | Solanaceae | Heavy feeder, arrives to the spring release | **deep** (24--36 in) |
| 3 | Cucurbits | Heavy feeder | broad, shallow--medium |
| 4 | Roots & chenopods | Wants the depleted ground -- excess N gives forked, hairy carrots | **deep** (12--24 in) |
| 5 | Alliums | Light feeder, poor weed competitor, benefits from following buckwheat's smother | **shallow** (6--12 in) |

Legume -> brassica -> heavy feeder -> low-N crop -> light feeder -> rebuild. Deep / shallow / deep / shallow, which keeps you from building a single compaction pan. On clay that's worth more than it would be on loam.

**What rotation genuinely controls.** Root-knot nematode is the clearest case: alliums and brassicas are poor hosts, solanaceae and cucurbits are good ones, and populations actually crash during non-host years rather than sitting dormant. Same for Colorado potato beetle, which overwinters near where it fed. These are real controls, not hedges.

**Verticillium is a backstop, not a driver.** UT's rule (no strawberries where potatoes, tomatoes, eggplant, peppers, or raspberries grew in the past 3 years) is a prophylactic default written for people managing acres. Under this map every section clears at least 5 years of non-host mobile crops between solanaceae and the next strawberry visit -- well beyond the 3-year minimum. Don't reorganize anything around it. If it's absent, rotation buys nothing; if it's present at high inoculum, rotation buys nothing either, since it persists 25+ years. It only pays in the narrow band where inoculum is present but low.

**The observation worth making:** at tomato cleanup, slice a stem near the base. Vascular browning in the outer ring = Verticillium. Thirty seconds, and it's worth more than any amount of planning.

---

## 4. The four rules that actually matter

Every disease in this plan arrives the same way: on planting stock. Introduction control is the primary; rotation is what catches its silent failures.

1. **Certified strawberry plugs** -- Verticillium
2. **Certified seed garlic** -- white rot. Never grocery-store cloves, never unknown provenance.
3. **BLS-screened pepper seed or transplants** -- bacterial leaf spot
4. **Grow your own brassica starts** -- clubroot

If you do only four things from this document, do these.

---

## 5. Solanaceae

One section, 12 x 3.5 ft = 42 sq ft. Single row at 24 in = **6 tomatoes**, staked. Two staggered rows would fit ~12 but leave 21 in between rows, and under Middle Tennessee Septoria pressure airflow beats plant count.

Six to eight is plenty. Peppers go in pots (see Pot Annex), which keeps the section at 6 tomatoes and the return at 5 years.

**What actually controls tomato disease here**, since rotation won't: resistant varieties, drip irrigation (never overhead), 2--3 in mulch to stop soil splash, stripping the lower 12 in of foliage, hard sanitation in November. Septoria and early blight are airborne and splash-borne and arrive every year regardless of what you plant where.

**Cadence:** radish/spinach/leaf lettuce Feb 20 -- Apr 10 (out before transplant date) -> tomatoes Apr 25 -- May 5 -> **relay-seed mache + arugula Oct 1--10** -> pull Nov 5.

---

## 6. Garlic and onions

They share the Allium section. Same family, same slot, both harvest in June. **Interplanted in alternating rows** across the full 12 ft section.

| Crop | Layout | Spacing | Yield |
|---|---|---|---|
| Garlic | Rows 1 & 3 (12 ft each) | 6 in in-row, 10 in between rows | 2 rows x 24 = **48 heads** |
| Onions | Rows 2 & 4 (12 ft each) | 4 in in-row, 10 in between rows | 2 rows x 36 = **72 bulbs** |

Yields are identical to the old half-and-half split. The interplanted layout eliminates the bare onion half from Oct--Feb and the cover crop that filled it.

Onions must be **intermediate-day** at 35.8 N (`Candy`, `Red Candy Apple`, `Superstar`). Long-day won't bulb; short-day bulbs too early and small.

| When | Action |
|---|---|
| Late Sep | Predecessor's buckwheat mowed and tilled |
| **Oct 15 -- Nov 10** | Garlic into rows 1 & 3, full 12 ft. UT: Sept--Nov across TN. |
| Nov | Straw mulch the garlic rows |
| Feb 20 -- Mar 10 | Onion transplants into rows 2 & 4, between established garlic |
| Mid--late Jun | Garlic first (watch for scapes), then onions 2--3 weeks later |
| Jul 1 | Buckwheat over the whole section |
| Aug 10 | Mow buckwheat at flowering (prevents reseeding) |
| Sep 1 | Clear. Hand off to strawberries (every 3rd cycle) or Gap C filler. |

**Harvest note:** garlic matures 2--3 weeks before onions. With alternating rows at 10 in spacing, loosen the garlic row from the bed edge with a fork, pull by hand. The onion rows are close but undisturbed if you work carefully. Easier than it sounds in a 3.5 ft bed.

**White rot** (*Sclerotium cepivorum*) ends garlic on a piece of ground permanently. Sclerotia survive **20--40 years** and can render soil unusable for alliums for as long as 40 years even with no host present. One sclerotium per 20 lb of soil causes measurable loss. No cure. Rotation doesn't control it; UC IPM is explicit that rotation alone will not, though it does prevent inoculum increase. It spreads on soil, equipment, and **especially infected cloves**. See rule #2.

Mildly in your favor: the fungus is restricted above 75 F and Middle Tennessee soils are warm.

---

## 7. The pot annex

Everything the rotation can't accommodate lives in containers on fresh media. That's not a compromise; fresh media annually is the most complete rotation there is.

| Goes in pots | Why |
|---|---|
| **Peppers** | Solanaceae; would crowd the tomatoes out of their one section |
| **Fall carrots** | Roots section hands to garlic on Oct 15 |
| **The July fall tomato crop** | No section is free at the right time |
| **Mint** | Must be contained regardless |

### Peppers

UT's spec: **8 in deep, 2--5 gallons**. A tomato wants 20. Eight 5-gal fabric pots = **$36 once, ~$13/yr in media, 5 sq ft** of patio edge.

Sow indoors **8--10 weeks before last frost** (~Feb 15), media at 75--80 F on a heat mat, 7--14 days to germinate. Transplant **early-to-mid May** -- later than the tomatoes, and for soil temperature, not frost. Early planting buys nothing when the ground is cold.

**Bells will stall in July and it isn't your fault.** UT: peppers prefer 70--75 F and extended periods above 86 F interfere with flowering and fruiting. Expect a June crop, a gap, then a September crop. Hot peppers hold up better for fruit set.

**Peri peri** is *C. frutescens*, same species as Tabasco: **85--105 days to ripe from transplant**. Set mid-May, ripe fruit mid-to-late August, running to frost. The unlock is that *C. frutescens* is a tender perennial -- **overwinter it in the pot.** In at frost, cut back hard, keep it barely alive by a window, back out in May. Year two starts established and fruits weeks earlier and much heavier. This is the reason peri peri belongs in a pot regardless of rotation.

**Varieties.** UT's bell list is a flavor guide, not a resistance list, and in the humid Southeast that's the wrong axis. Bacterial leaf spot is one of the most destructive pepper diseases in the eastern US, most strains are now copper-resistant, and resistant varieties are the only real control -- Clemson notes fully resistant varieties don't need spraying at all. Choose bells resistant to all ten races of *Xanthomonas euvesicatoria*: `Antebellum`, `Green Machine`, `Ninja S10`, `Prowler` (Clemson, Southeast); `Nitro S10`, `Sailfish`, `Tarpon` (Cornell, also Phytophthora-resistant); `Turnpike` (races 0--5, 7--9). Jalapenos per UT: `Emerald Fire`, `Spicy Slice`, `El Jefe`.

---

## 8. The winter gaps

Three named gaps per rotation cycle, all opening in autumn or late summer. Everything else is 19--36 days and not worth planting.

| After | Frees | Before | Needs | Idle | Label |
|---|---|---|---|---|---|
| Solanaceae | Nov 5 | Cucurbits | May 5 | **182 d (6.0 mo)** | **Gap A** |
| Cucurbits | Nov 5 | Roots | Mar 1 | **117 d (3.8 mo)** | **Gap B** |
| Alliums | Sep 1 | Leg -> Brass | Jul 1 | **303 d (10.0 mo)** | **Gap C** |
| Legumes -> Brassicas | Jan 15 | Solanaceae | Feb 20 | 36 d | |
| Strawberries (yr 3) | Jun 10 | Legumes | Jul 1 | 21 d | |
| Roots | Sep 25 | Alliums | Oct 15 | 20 d | |
| Alliums | Sep 1 | Strawberries | Sep 20 | 19 d | |

**Gap C** is specific to the 5+1 system. It occurs 2 out of every 3 times a section finishes Alliums -- whenever strawberries don't intercept. The section sits idle Sep 1 -> Jul 1 (303 d). Filled with mache + arugula, it produces winter greens instead of bare soil.

With fillers in all three named gaps, truly idle time drops to **~3%** of the cycle (the 19--36 d short gaps only).

### Why Gaps A and B default to rye, and how to fix them

Both long gaps open **Nov 5**, past the sowing window for every winter food crop:

| Crop | Last sow | vs Nov 5 |
|---|---|---|
| Daikon / tillage radish | ~Sep 15 | missed by 51 d |
| Kale | ~Oct 1 | missed by 35 d |
| Spinach, mache, winter peas | ~Oct 15 | missed by 21 d |
| **Cereal rye** | ~Nov 15 | **OK** |

Rye isn't the best crop for those gaps, it's the only one still plantable that late. **Fix the window, not the seed.**

**Gap A (182 d): relay-seed Oct 1--10 under the standing tomatoes.** Single staked row in a 3.5 ft bed means open ground on both sides. Broadcast mache + arugula while the tomatoes are still fruiting; pull them Nov 5 and the filler already has four weeks on it. Or just pull the tomatoes Oct 1 -- late-October tomatoes ripen slowly anyway. Must clear by **May 5**; generous, since both bolt or finish naturally by then.

**Gap B (117 d): skip the second squash planting.** Vine borer and powdery mildew usually finish the main planting by early September regardless. Skipping the Aug 19--24 second sowing opens the gap **Sept 1** and puts everything back in range. Must clear by **Mar 1**; tight, so kale and spinach are poor picks here since they'd still be producing. Mache clears naturally; arugula can be pulled if it lingers.

**Gap C (303 d): sow Sep 1 after Alliums clear.** The longest gap, but also the easiest to fill -- it opens in September, when every winter crop is still in range. Sow mache + arugula Sep 1, harvest through winter and spring. Optional spring follow-on (lettuce, radish) after the winter greens finish, as long as everything clears by Jul 1 for incoming Legumes.

### Filler picks

| Crop | Family | Gap A (Oct->May) | Gap B (Sep->Mar) | Gap C (Sep->Jul) |
|---|---|---|---|---|
| **Mache / corn salad** | Valerianaceae | **clean -- no conflict anywhere** | **clean** | **clean -- primary pick** |
| **Arugula** | Brassicaceae | **clean** (see note) | **clean** | **clean -- pair with mache** |
| **Daikon / tillage radish** | Brassicaceae | tight (1.5 yr to next brassica) | **best -- 2.5 yr, clears by Jan, drills clay** | OK |
| Kale, turnip, mustard | Brassicaceae | tight (1.5 yr) | won't clear by Mar 1 | OK but unnecessary |
| Austrian winter peas | Fabaceae | tight (1.5 yr) | OK (2.5 yr), N-fixer, eat the tendrils | OK |
| Spinach | Chenopodiaceae | tight (1.5 yr to next chenopod) | **avoid** -- lands 6 months before the beet/chard year | OK |
| Cereal rye | Poaceae | no conflict, not food | no conflict, not food | no conflict, not food |

**Mache + arugula is the standard filler pair for all three gaps.** Mache (Valerianaceae) has zero rotation conflict anywhere. Arugula is Brassicaceae but safe as a filler: harvested as baby greens (minimal debris left in soil), biofumigant properties suppress soil pathogens rather than harboring them, and the minimum gap to the next brassica year is 3.5+ years. Cornell's cover crop guide warns against arugula in brassica rotations, but that guidance assumes field-scale debris incorporation; baby-green harvest in raised beds at pH >7.2 with good drainage is a different risk profile.

Clubroot note, since several fillers are brassicas: it's favored by pH below 6.5 and wet soil, suppressed above **7.2**. Your beds sit on limestone-derived ground with 193 mg/L irrigation water, and raised beds drain. Risk is low. Soil test annually; if bed pH drifts below 7, use **calcitic** lime (not dolomitic, unless magnesium is low).

**On rye grain:** yes, *Secale cereale* is the rye in rye bread. But the plan kills it in February; it never heads. Letting it make grain costs the section its whole spring for **~2.2 lb** (40 bu/acre x 42 sq ft), worth about $5, plus hand threshing. Same arithmetic kills wheat, corn, and buckwheat grain. Grain is a field crop.

---

## 9. The other groups

### Legumes -> Brassicas
Southern peas Jul 1 -- following either pulled strawberries (yr 3) or cleared Gap C filler -> fall brassicas transplanted Aug 13--28, started indoors Jul 2--24 -> harvest Nov--Dec, sweeter after frost. Chop residue in unless diseased; it has a documented biofumigant effect.

### Cucurbits
Filler A carries through -> squash / cucumber May 5--15 -> **skip the second planting**, sow Filler B Sept 1. Melons are fine.

*Species matters more than variety.* Pattypan, zucchini, yellow crookneck, and acorn are all *Cucurbita pepo*, the vine borer's preferred host. *C. moschata* has thick, corky, solid-pith stems that are a poor host and handles heat and humidity better. **Tromboncino** (Zucchetta Rampicante) is a *moschata* eaten young exactly like zucchini; left to mature it stores as winter squash. Trellis on the north edge. If you keep *pepo*, row-cover from transplant until heavy flowering, then remove for pollinators.

### Roots & chenopods
Filler B carries through -> spring carrots, beets, chard Mar 1 -> harvest Jun -> **buckwheat Jul--late Sep**, mowed and tilled before garlic. No fall carrots (this section hands to garlic on Oct 15); use a deep pot.

### Strawberries
**3-year stay, then rotate.** Order certified plugs Jul 15 (planting year only) -> set Sep 20 -> row cover Jan for hard freezes -> bloom late Mar (watch frost) -> harvest Apr 20 -- May 25.

**Annual renovation** after years 1 and 2: mow foliage 1 week post-harvest, thin runners to 4--6 in spacing, side-dress with balanced fertilizer. **Pull after year 3** harvest (Jun 10). The vacated section receives Legumes (Jul 1 peas).

Strawberries always follow Alliums when they move (Alliums clear Sep 1 -> plugs Sep 20). Next strawberry planting in the same section: **18 years** (6 sections x 3 years). Plug ordering and planting happen only every 3rd year.

Plasticulture is optional with a 3-year stay. Raised-bed plastic mulch still suppresses weeds and keeps fruit clean, but a 3-year planting can also run as a modified matted row with annual renovation. Either way, the introduction-control rule applies: certified plugs only (see The Four Rules).

---

## 10. Fall back-count table

UT's method: **days to maturity + 10** (fall growth is slower under declining light), counted back from the end of the useful harvest window.

| Crop | DTM | +10 | Set/seed in bed | Start indoors |
|---|---|---|---|---|
| Cabbage | 75 | 85 | **Aug 13** | Jul 2 |
| Carrots | 70 | 80 | Aug 18 | -- |
| Bush beans (last) | 55 | 65 | **Aug 19** | -- |
| Cucumber (last) | 55 | 65 | **Aug 19** | -- |
| Summer squash (last) | 50 | 60 | **Aug 24** | -- |
| Broccoli | 60 | 70 | **Aug 28** | Jul 17 |
| Collards | 60 | 70 | **Aug 28** | Jul 24 |
| Kale | 55 | 65 | **Sep 2** | -- |
| Beets | 55 | 65 | **Sep 2** | -- |
| Turnips | 50 | 60 | **Sep 7** | -- |
| Spinach | 40 | 50 | **Sep 17** | -- |
| Leaf lettuce | 35 | 45 | **Sep 22** | -- |

**The habit that unlocks the system:** seed fall brassicas **July 2--24**, while it's 95 degrees and broccoli is the last thing on your mind. Miss it and there's no fall crop. Phone alarm.

**Fall tomatoes (in pots):** Jul 1 set, 70-day determinate -> first fruit Sep 9, 44 days of harvest before frost. Determinates only.

---

## 11. Patio herb beds

Rosemary, thyme, sage, and oregano are **perennials** in 7a. Only basil (warm-season) and cilantro (cool-season) are annuals. The two halves want opposite soil, so build **two zones**.

### Perennial zone
**~50% coarse grit or #57 washed gravel / 30% topsoil / 20% compost.** Raised 8--12 in, crowned to shed. Not the 40/50/10 bed mix -- too rich, too water-retentive. Rosemary here dies from wet feet in winter, not cold. Your slope is an asset.

| Plant | Mature size | Spacing | Count | Placement |
|---|---|---|---|---|
| Rosemary | 3--4 ft x 3--4 ft | 3 ft | 1 | Anchor at the entry, where you brush past it |
| Sage | 2--2.5 ft | 2 ft | 1--2 | Back |
| Greek oregano | 12--18 in, spreads | 18 in | 2 | Mid |
| Thyme | 6--12 in, spreads 18 in | 12--18 in | 3 | **Edge**, spilling over paving |

~4 x 8 ft, or two 3 x 4 ft pockets flanking the patio.

Cultivars (UT): rosemary `Arp`, `Blue Boy`, `Golden Rain` -- `Arp` and `Madeline Hill` are the cold-hardy ones, and this matters; a non-hardy rosemary in a wet 7a winter is a coin flip. Thyme `German Winter`, `Summer`, `Orange`. `Greek Oregano`. `Common sage`.

### Annual zone
Basil and cilantro have opposite seasons, which makes them a succession pair. Three crops, one 3 x 4 ft footprint:

| When | Crop |
|---|---|
| Feb 20 -- Apr | Cilantro (re-sow every 2--3 wks) |
| ~Late May | Let the last one bolt -> **coriander seed in June** |
| May 10 -- Oct | Basil (4--6 plants, 12--18 in) |
| Sep -- Nov | Cilantro again |

Normal mix here. This is also where a fall carrot crop can live.

**Basil downy mildew** is brutal in humid Southeast summers. UT's list is resistance-heavy for a reason: `Devotion`, `Obsession`, `Newton`, `Nufar`, `Aroma II`, `Prospera Compact`, `Everleaf`. Garden-center Genovese will not survive August. Cilantro: `Calypso` is the slowest to bolt.

**Siting.** The mid-yard bare patch is almost certainly summer-dormant tall fescue, not dead ground -- that drone shot is July 7. Site for sun and access, not the brown spot. It's your sunniest open ground, which is why the pots belong there too.

**Notes.** Cilantro is Apiaceae, same family as the Group 4 carrots; growing it only at the patio is cleaner than splitting the family across two areas, and its main diseases are seedborne rather than soil-persistent. Parsley is the one to watch, being biennial. Mint goes in a standalone container. Basil doesn't belong in the perennial zone.

---

## 12. Standing annual calendar

Template dates for recurring actions. The dossier instantiates these against
actual section assignments each year.

| Date | Action |
|---|---|
| Jan | Advance the march one row (mobile groups only; mark strawberry year count). Order seed, **certified seed garlic**, **BLS-screened pepper seed**. **Order certified strawberry plugs if this is a planting year** (every 3rd year). |
| **Feb 15** | **Seed peppers indoors** (8--10 wks, heat mat at 75--80 F) |
| Feb 20 | Seed tomatoes indoors |
| Feb 20 -- Mar 10 | Onion transplants into the Allium section (between established garlic) |
| Feb 20 -- Apr 10 | Spring greens into the Solanaceae section; cilantro at the patio |
| **Mar 1** | **Filler B out. Spring carrots/beets/chard into the Roots section.** |
| Apr 25 -- May 5 | Tomato transplants |
| **May 5** | **Filler A out. Squash/cucumber into the Cucurbits section.** |
| May 5 -- 15 | Peppers into pots (soil temperature, not frost date). Basil at the patio. |
| **Jun 10** | **Strawberries: renovate (yr 1--2) or pull (yr 3).** |
| Mid--late Jun | Garlic first (watch for scapes), then onions 2--3 weeks later. |
| **Jul 1** | **Southern peas into post-strawberry or post-Gap-C section; buckwheat into Roots and Alliums. Fall tomatoes into pots.** |
| **Jul 2 -- 24** | **Seed fall brassicas indoors** |
| Jul 15 | Order strawberry plugs (planting year only) |
| Aug 10 | Mow the Allium buckwheat at flowering |
| **Aug 13 -- 28** | **Fall brassica transplants out** |
| **Sep 1** | **Allium section clear. Sow mache + arugula: Filler B into Cucurbits; Gap C filler into Allium section (if going to Leg -> Brass).** |
| **Sep 20** | **Strawberry plugs in (planting year only)** |
| Late Sep | Roots section's buckwheat mowed and tilled |
| **Oct 1 -- 10** | **Relay-seed mache + arugula (Filler A) under the standing tomatoes** |
| **Oct 15 -- Nov 10** | **Garlic into the Allium section.** Straw mulch in November. |
| Oct | Soil test. pH moves take months. Check beds stay above pH 7. |
| Oct 20 -- Nov 5 | Pull all Solanaceae. **Slice a stem -- check for vascular browning.** Sanitation. |
| Nov -- Dec | Overwinter the peri peri indoors. Dump and refill the pots. |

---

## 13. Known limits

1. **Solanaceae is one section.** 6 tomatoes. Peppers in pots hold your total.
2. **Fall carrots don't fit.** Spring only in the beds; use a pot.
3. **Garlic and onions interplant in alternating rows** across the full section -- yields are identical to the old half-and-half split (48 garlic, 72 onions). Harvest garlic first; onions follow 2--3 weeks later.
4. **~3% of the cycle is truly idle** (the 19--36 d short gaps). Fillers A, B, and C convert the three long gaps to food production.
5. **Rotation won't beat Septoria, early blight, or Verticillium.** It's real for nematodes, Colorado potato beetle, and the nutrient cascade. For the rest, see The Four Rules.
6. **Strawberry return is 18 years per section.** Long, but a 3-year stay with renovation produces more fruit per plug investment than annual replanting.

---

## 14. Open options

**Sweet potato, swapped for Cucurbits.** *Ipomoea batatas* is Convolvulaceae, a family appearing nowhere else here. Slips mid-May, harvest ~Sept 2. The real pitch is succession: that section currently frees Nov 5, which is why Gap A defaults to rye -- sweet potato frees Sept 2 and puts kale, daikon, mache, and winter peas back in range without the relay trick. Plus clay and heat tolerance, high yield per square foot, and it stores in a closet instead of needing canning in August. Costs you squash and cucumbers from the beds, since squash pots poorly. Revisit after a season.

**Grafted tomatoes**, if you ever want 2 Solanaceae sections at a 3-year return. `Maxifort` (Verticillium/Fusarium), `Armada` or `Shincheonggang` (bacterial wilt). Keep the union above the soil line permanently or you've wasted the money. Currently unnecessary at 6--8 plants.

**Berry beds.** Prune the overhanging limbs first, then measure actual sun hours before deciding anything. Your shade allocation is inverted -- blackberries (most sun-demanding) sit at the shaded outer ends while the open center holds the more shade-tolerant blueberries. When the blueberries vacate the center, move canes in rather than adding more at the ends. Separately, UT's fruit specialist notes raspberries are a cool-season crop and heat tolerance is the major issue in this region, so mediocre raspberries may not be a shade problem at all.

**Blueberry bed.** Right call, but: don't use the 40/50/10 mix (compost sits above pH 7 and blueberries are salt-sensitive) -- use 50--80% aged fine bark, 10--40% peat, 10% perlite. Move them **dormant, Dec--Feb**, not in summer. Six plants at rabbiteye spacing is a 36 ft row (~5 cu yd of media, $450--530); a two-row block is likelier to fit. Put a rain barrel on the nearest downspout: 193 mg/L irrigation water will steadily push the bed's pH up, and UGA notes South Georgia's pine-bark blueberry beds never need liming precisely because alkaline well water does it for them. Keep it 4+ ft off the foundation.

**Plum/peach.** Removed Aug 2026 to extend the north bed. If stone fruit is wanted later, site it in-ground away from the beds.

---

## Sources

- UT Extension **W436**, *Tennessee Home Fruit and Vegetable Garden Calendar* -- frost dates, back-count method, crop families, rotation rule, garlic window, cover crops, herb cultivars
- UT Extension **D60**, *Peppers for the Tennessee Vegetable Garden* -- Solanaceae rotation, container spec, 86 F flowering threshold, spacing, variety table
- UT Extension Master Gardener **Ch. 12** -- strawberry/Verticillium 3-year rule; **W316** -- rotation efficacy
- Ohio State **PLPATH-FRU-32** / Illinois **RPD 707** -- Verticillium hosts, 25-yr persistence
- Ohio State **VegNet** -- rotation limits on wide-host pathogens, rootstocks
- Clemson **Land-Grant Press** / Cornell Vegetables -- BLS-resistant peppers; NC State -- bacterial wilt rootstocks, clubroot pH
- UC IPM, U. Maryland, U. Maine **#2062**, PNW Handbook, UMass -- allium white rot
- Clemson HGIC, Cornell, Purdue, MOFGA -- *C. moschata* vine borer resistance
- UGA -- pine bark blueberry beds, alkaline irrigation water; CUD Rutherford County -- 193 mg/L hardness
- Cornell cover crop guide -- arugula in brassica rotations; biofumigant properties
- Sustainable Market Farming (Pam Dawling) -- Zone 7a late spinach sowing windows
