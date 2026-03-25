# Cross-Document Hyperlinks and Bookmarks

This reference provides strict rules for generating safe and clickable hyperlinks between Word `.docx` documents.

## Common Failure Scenarios

The goal is to prevent:
- Non-clickable hyperlinks (text looks blue but nothing happens)
- Corrupted DOCX files
- Word open failures ("Word experienced an error trying to open the file")
- Bookmark conflicts
- Relationship ID collisions

---

## Word Navigation Model

Word navigation works as:

```
source_doc hyperlink
       ↓
target_doc.docx
       ↓
     bookmark
```

**CRITICAL: Word cannot jump to page numbers directly.**

| Format | Valid? | Reason |
|--------|--------|--------|
| `docB.docx#page=15` | ❌ INVALID | Page numbers are layout results |
| `docB.docx#page_15` | ✅ VALID | Jump target is a bookmark |

The jump target must always be a **bookmark**.

---

## Bookmark Strategy

Bookmarks must exist in the target document.

**Naming convention:**

| Pattern | Examples |
|---------|----------|
| `page_{page_number}` | `page_15`, `page_120` |
| `section_{id}` | `section_3_2` |
| `FUNC_{id}` | `FUNC_0007` |
| `REQ_{id}` | `REQ_1023` |

**Rules:**
- Bookmark names must be unique
- Bookmark names must not contain spaces
- Use only `[A-Za-z0-9_]`

---

## Bookmark XML Pattern

Bookmarks must be created as **paired nodes** in Word OOXML.

**Correct pattern:**

```xml
<w:bookmarkStart w:id="15" w:name="page_15"/>
<w:r>
  <w:t>Target Text</w:t>
</w:r>
<w:bookmarkEnd w:id="15"/>
```

**Rules:**
- `bookmarkStart` and `bookmarkEnd` must share the same `w:id`
- Missing `bookmarkEnd` will break Word navigation
- Bookmark IDs must be unique

**Safe placement at paragraph level:**

```xml
<w:p>
  <w:bookmarkStart w:id="10" w:name="page_15"/>
  <w:r>
    <w:t>Target content</w:t>
  </w:r>
  <w:bookmarkEnd w:id="10"/>
</w:p>
```

---

## Hyperlink Construction Rule

A Word hyperlink MUST contain a run element and MUST apply the **Hyperlink style**.

**Mandatory components:**
- `<w:hyperlink>` must wrap `<w:r>`
- `<w:r>` must contain `<w:t>`
- `<w:rPr>` must include `<w:rStyle w:val="Hyperlink"/>`

**Correct example:**

```xml
<w:hyperlink r:id="rId25">
  <w:r>
    <w:rPr>
      <w:rStyle w:val="Hyperlink"/>
    </w:rPr>
    <w:t>Jump to page 15</w:t>
  </w:r>
</w:hyperlink>
```

**Without the Hyperlink style, the text may appear normal and will not be clickable.**

---

## Internal vs Cross-Document Links

| Link Type | Attribute | Example |
|-----------|-----------|---------|
| Internal (same document) | `w:anchor` only | `<w:hyperlink w:anchor="FUNC_0007">` |
| Cross-document | `r:id` only | `<w:hyperlink r:id="rId25">` |

**CRITICAL: Never mix them.**

```xml
<!-- ❌ INVALID: Both r:id and w:anchor on cross-document link -->
<w:hyperlink r:id="rId25" w:anchor="FUNC_0007">
```

For cross-document links, the bookmark name goes in the Relationship `Target`, not in `w:anchor`.

```xml
<!-- Relationship entry -->
<Relationship Id="rId25" Type=".../hyperlink" Target="docB.docx#page_15" TargetMode="External"/>
```

---

## Relationship Table (CRITICAL)

Every cross-document hyperlink must have a relationship entry.

**File location:** `word/_rels/document.xml.rels`

```xml
<Relationship
    Id="rId25"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    Target="docB.docx#page_15"
    TargetMode="External"/>
```

**Rules:**
- Relationship `Id` must match hyperlink `r:id`
- `Target` must contain the document name AND bookmark
- `TargetMode="External"` is required

**If the relationship entry is missing: The hyperlink may look correct but will not be clickable.**

---

## rId Collision Prevention

When generating many hyperlinks, ensure:
- `rId` numbers are unique
- New `rId` must not overwrite existing ones

**Safe strategy:**

```bash
# 1. Scan existing rIds in word/_rels/document.xml.rels
# 2. Calculate: max_rId + 1
# 3. Use that for new hyperlink
```

Example:

| Existing rIds | New hyperlink rId |
|---------------|-------------------|
| rId1, rId2, rId3 | rId4 |

---

## Bookmark ID Strategy

Bookmark IDs must also remain unique.

**Safe rule:**
- Scan existing bookmark IDs in `document.xml`
- Use `max_id + 1` for new bookmarks
- Never reuse IDs

---

## Large-Scale Hyperlink Management

**CRITICAL: When documents contain thousands of hyperlinks, the most common failure is:**
- Relationship file bloat
- rId sequence corruption

**Industrial-grade strategy:**

```
Every 500 hyperlinks
→ Rebuild relationship index
```

This means:
1. Scan all hyperlinks in `document.xml`
2. Renumber relationships starting from `rId1`
3. Update all `r:id` references in `document.xml`

---

## Safe Hyperlink Creation Workflow

### Step 1: Insert Bookmark in Target Document

```xml
<!-- In target document (docB.docx) -->
<w:p>
  <w:bookmarkStart w:id="15" w:name="page_15"/>
  <w:r><w:t>Content on page 15</w:t></w:r>
  <w:bookmarkEnd w:id="15"/>
</w:p>
```

### Step 2: Create Hyperlink Text in Source Document

Example text: `Jump to Page 15`

### Step 3: Add Hyperlink XML

```xml
<!-- In source document (docA.docx) -->
<w:hyperlink r:id="rId25">
  <w:r>
    <w:rPr>
      <w:rStyle w:val="Hyperlink"/>
    </w:rPr>
    <w:t>Jump to Page 15</w:t>
  </w:r>
</w:hyperlink>
```

### Step 4: Insert Relationship Entry

In `word/_rels/document.xml.rels`:

```xml
<Relationship
    Id="rId25"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    Target="docB.docx#page_15"
    TargetMode="External"/>
```

### Step 5: Validate XML Structure

Run validation to ensure DOCX integrity.

---

## Known Failure Patterns and Diagnosis

| Symptom | Cause | Solution |
|---------|-------|----------|
| Hyperlink looks blue but cannot click | Missing relationship entry | Add entry to `document.xml.rels` |
| Hyperlink looks blue but cannot click | Missing `Hyperlink` style | Add `<w:rStyle w:val="Hyperlink"/>` to `<w:rPr>` |
| Word navigation fails | Missing `bookmarkEnd` | Add matching `<w:bookmarkEnd w:id="X"/>` |
| "Word experienced an error trying to open the file" | Broken XML structure | Check unclosed tags, invalid nesting |
| Word ignores hyperlink target | Invalid bookmark name | Remove spaces, use only `[A-Za-z0-9_]` |
| Hyperlinks point to wrong location | rId collision | Scan and use unique rId |
| Cross-document link doesn't work | Using `w:anchor` instead of `r:id` | Use `r:id` for cross-document |

---

## Validation Checklist (MANDATORY)

Before finishing, the agent must verify:

### Bookmark validation:
- [ ] `bookmarkStart` exists in target document
- [ ] `bookmarkEnd` exists in target document
- [ ] Bookmark `w:id` values match between start and end
- [ ] Bookmark names are valid (no spaces, only `[A-Za-z0-9_]`)
- [ ] Bookmark IDs are unique

### Hyperlink validation:
- [ ] Hyperlink contains `r:id` (cross-document) or `w:anchor` (internal)
- [ ] Hyperlink contains `<w:r>` with `<w:t>`
- [ ] Hyperlink run includes `<w:rStyle w:val="Hyperlink"/>`
- [ ] Cross-document links do NOT have both `r:id` and `w:anchor`

### Relationship validation:
- [ ] Relationship entry exists in `word/_rels/document.xml.rels`
- [ ] Relationship `Id` matches hyperlink `r:id`
- [ ] `TargetMode="External"` is set
- [ ] Target contains document name AND bookmark

### Document integrity:
- [ ] DOCX ZIP structure intact
- [ ] Target file exists
- [ ] No unclosed XML tags
- [ ] XML namespaces preserved

---

## Golden Rule

**A working hyperlink requires three components:**

1. **Bookmark definition** (in target document)
2. **Hyperlink node** (in source document)
3. **Relationship entry** (in source document's `document.xml.rels`)

If any one is missing, the hyperlink will fail.
