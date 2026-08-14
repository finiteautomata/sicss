import json
import tempfile

import gradio as gr

CATEGORIES = [
    ("Sexism / Misogyny", "WOMEN"),
    ("Homophobia / Transphobia", "LGBTI"),
    ("Racism / Xenophobia", "RACISM"),
    ("Social class", "CLASS"),
    ("Political affiliation", "POLITICS"),
    ("Disability", "DISABLED"),
    ("Physical appearance", "APPEARANCE"),
    ("Criminal behavior", "CRIMINAL"),
]
CATEGORY_KEYS = [key for _, key in CATEGORIES]


def load_data(path="sample.json"):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


DATA = load_data()


def tweet_embed_html(tweet_id: str) -> str:
    return f"""
<iframe
  src="https://platform.twitter.com/embed/Tweet.html?id={tweet_id}"
  style="width:100%;min-height:280px;border:none;border-radius:12px;"
  sandbox="allow-scripts allow-popups allow-same-origin allow-top-navigation-by-user-activation"
  loading="lazy">
</iframe>"""


def progress_bar_html(all_labels: dict) -> str:
    labeled = sum(1 for item in DATA if item["id"] in all_labels)
    pct = int(labeled / len(DATA) * 100)
    return f"""
<div style="margin:4px 0 8px 0;">
  <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px;">
    <span>{labeled} of {len(DATA)} labeled</span><span>{pct}%</span>
  </div>
  <div style="background:#e5e7eb;border-radius:8px;height:10px;">
    <div style="background:#6366f1;width:{pct}%;height:10px;border-radius:8px;transition:width 0.3s;"></div>
  </div>
</div>"""


def render_item(idx: int, all_labels: dict):
    item = DATA[idx]
    label = all_labels.get(item["id"], {})
    hateful = label.get("HATEFUL", False)
    calls = label.get("CALLS", False)
    cats = label.get("categories", [])
    progress = f"**Comment {idx + 1} of {len(DATA)}**"
    embed = tweet_embed_html(item["article_id"])
    comment = item["text"]
    return embed, comment, progress, hateful, calls, cats, gr.update(visible=hateful)


def save_current(idx, all_labels, hateful, calls, categories):
    item = DATA[idx]
    all_labels = dict(all_labels)
    all_labels[item["id"]] = {
        "HATEFUL": hateful,
        "CALLS": calls if hateful else False,
        "categories": list(categories) if hateful else [],
    }
    return all_labels


def navigate(idx, all_labels, hateful, calls, categories, direction):
    at_end = direction == 1 and idx == len(DATA) - 1
    all_labels = save_current(idx, all_labels, hateful, calls, categories)
    new_idx = max(0, min(len(DATA) - 1, idx + direction))
    embed, comment, progress, h, c, cats, details_vis = render_item(new_idx, all_labels)
    pbar = progress_bar_html(all_labels)
    finish_vis = gr.update(visible=at_end)
    return new_idx, all_labels, embed, comment, progress, h, c, cats, details_vis, pbar, finish_vis


def build_output(all_labels: dict, annotator: str) -> list:
    rows = []
    for item in DATA:
        label = all_labels.get(item["id"])
        if label is None:
            rows.append({
                "id": item["id"],
                "tweet_id": item["tweet_id"],
                "article_id": item["article_id"],
                "text": item["text"],
                "annotator": annotator,
                "HATEFUL": None,
                "CALLS": None,
                **{k: None for k in CATEGORY_KEYS},
            })
        else:
            rows.append({
                "id": item["id"],
                "tweet_id": item["tweet_id"],
                "article_id": item["article_id"],
                "text": item["text"],
                "annotator": annotator,
                "HATEFUL": label["HATEFUL"],
                "CALLS": label["CALLS"],
                **{k: k in label["categories"] for k in CATEGORY_KEYS},
            })
    return rows


def download_labels(all_labels, annotator):
    rows = build_output(all_labels, annotator or "anonymous")
    labeled = sum(1 for r in rows if r["HATEFUL"] is not None)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(rows, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return gr.update(visible=True, value=tmp.name), f"**{labeled}/{len(DATA)} comments labeled** — file ready to download."


with gr.Blocks(title="Tweet Comment Labeler") as app:
    idx_state = gr.State(0)
    labels_state = gr.State({})

    gr.Markdown("# Tweet Comment Labeling Tool")

    with gr.Row():
        annotator_box = gr.Textbox(
            label="Your name / annotator ID",
            placeholder="e.g. student_01",
            scale=2,
        )
        progress_md = gr.Markdown(f"**Comment 1 of {len(DATA)}**", scale=1)

    pbar_html = gr.HTML(progress_bar_html({}))

    finish_banner = gr.Markdown(
        "## ¡Terminaste! 🎉 Ya anotaste todos los comentarios. Descargá tus anotaciones abajo.",
        visible=False,
    )

    with gr.Row():
        with gr.Column(scale=3):
            gr.Markdown("### Original tweet (context)")
            embed_html = gr.HTML(tweet_embed_html(DATA[0]["article_id"]))

            gr.Markdown("### Comment to label")
            comment_box = gr.Textbox(
                value=DATA[0]["text"],
                label="",
                interactive=False,
                lines=3,
            )

        with gr.Column(scale=2):
            gr.Markdown("### Labels")

            hateful_check = gr.Checkbox(label="HATEFUL — contains hate speech", value=False)

            with gr.Group(visible=False) as hate_group:
                calls_check = gr.Checkbox(label="CALLS FOR ACTION — incites others to act against a target")

                cat_check = gr.CheckboxGroup(
                    choices=CATEGORIES,
                    label="Offensive categories (select all that apply)",
                    value=[],
                )

            hateful_check.change(
                fn=lambda h: gr.update(visible=h),
                inputs=[hateful_check],
                outputs=[hate_group],
            )

    with gr.Row():
        prev_btn = gr.Button("← Previous", variant="secondary", scale=1)
        next_btn = gr.Button("Next →", variant="primary", scale=1)

    gr.Markdown("---")

    with gr.Row():
        dl_btn = gr.Button("Download my labels as JSON", variant="secondary")
        dl_status = gr.Markdown("")

    dl_file = gr.File(label="", visible=False)

    # Navigation
    nav_outputs = [
        idx_state, labels_state,
        embed_html, comment_box, progress_md,
        hateful_check, calls_check, cat_check, hate_group,
        pbar_html, finish_banner,
    ]
    nav_inputs = [idx_state, labels_state, hateful_check, calls_check, cat_check]

    next_btn.click(
        fn=lambda *a: navigate(*a, direction=1),
        inputs=nav_inputs,
        outputs=nav_outputs,
    )
    prev_btn.click(
        fn=lambda *a: navigate(*a, direction=-1),
        inputs=nav_inputs,
        outputs=nav_outputs,
    )

    dl_btn.click(
        fn=download_labels,
        inputs=[labels_state, annotator_box],
        outputs=[dl_file, dl_status],
    )


if __name__ == "__main__":
    app.launch(theme=gr.themes.Soft())
