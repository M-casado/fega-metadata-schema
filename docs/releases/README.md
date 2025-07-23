# Release and versioning guide
Each JSON Schema must be **resolvable at a stable URL** so external validators and Biovalidator instances can fetch _exactly_ the version they expect.  
We therefore tag every published set of schemas, rewrite (where applicable) all internal `$id` / `$ref` pointers to that immutable tag, and capture the versions in a machine-readable manifest.  

Most of these steps are automated by the following resources:
- [``schema_diff.py``](../../scripts/py/schema_diff.py). Used to check SemVer differences (e.g., ``major``) between two sources (e.g., branch ``dev`` and ``main``).
- [``check_schema_diff.yml``](../../.github/workflows/check_schema_diff.yml). Can be triggered manually to quickly check SemVer differences through ``schema_diff.py``.
- [``check_meta_enums.yml``](../../.github/workflows/check_meta_enums.yml). In a PR, used to assert that a all ``meta:enum`` fields of the JSON Schemas correspond to the true changes between the source and target branches.
- [``modify-ids.py``](../../scripts/py/modify-ids.py). Enables an quick and easy modification of the static pointers in the JSON Schemas (`$id` / `$ref` / ``@context``).
- [``update_release_manifest.py``](../../scripts/py/update_release_manifest.py). Automatically updates the [``release_manifest.json``](release_manifest.json) file.
- [``create_release.yml``](../../.github/workflows/create_release.yml). If triggered, it automates the first steps of a release.

## Branching and tags

| Name | Purpose | `$id`/`$ref` segment | Example |
|------|---------|----------------------|---------|
| `main` branch | latest **stable** snapshot | `/main/` | https://raw.githubusercontent.com/M-casado/fega-metadata-schema/main/schemas/FEGA.cohort.json |
| `dev`  branch | day-to-day work (unstable) | `/dev/` | https://raw.githubusercontent.com/M-casado/fega-metadata-schema/dev/schemas/FEGA.cohort.json |
| `vX.Y.Z` branch | frozen candidate | `/vX.Y.Z/` | https://raw.githubusercontent.com/M-casado/fega-metadata-schema/v1.0.0/schemas/FEGA.cohort.json |
| `vX.Y.Z` tag | final, immutable release | `/vX.Y.Z/` | https://raw.githubusercontent.com/M-casado/fega-metadata-schema/v1.0.0/schemas/FEGA.cohort.json |

````mermaid
gitGraph
   commit id:"start" tag: "/main/"
   branch dev
   checkout dev
   commit id:"feature-work"
   commit id:"more-work" tag: "/dev/"

   branch v2.0.1 
   checkout v2.0.1
   commit id:"1st-pointer-rewrite" tag: "/v2.0.1/"
   commit id:"update_release_manifest"
   
   branch release
   checkout release 
   commit id: " " tag: "/v2.0.1/"

   checkout v2.0.1
   commit id:"2nd-pointer-rewrite" tag: "/main/"


   %% PR release → main (fast-forward)
   checkout main
   merge v2.0.1 tag: "/main/"

   %% tag & GitHub Release
   checkout v2.0.1

   %% back to dev continues
   checkout dev
   commit id:"post-release work"
````

## Process overview

* **Validation gate**: every push to `dev` must still pass schema self-validation.  
* **Semantic diff**: a CI job compares `dev` vs `main` and reports the required Semantic Versioning bump (major / minor / patch).  
* **Release action**: triggered from GitHub Actions UI.  
  * Input: `release_version` (e.g. `2.1.0`).  
  * Creates release branch (e.g., `v2.1.0`), rewrites pointers from `/dev/` → `/v2.1.0/`, updates `release_manifest.json`.  
* **Human review**: PR `v2.1.0` → `main` lets a maintainer inspect the changes introduced in the new release and update the appropriate changelog snippet.
* **GitHub Release**: Triggering the release from the release branch creates a new stable tag (e.g., `v2.1.0`) that replaces the branch URI when removed, uploads a ZIP of the whole repository and publishes the changelog.
* **Updating main**: Once the release is created, we rewrite static pointers in the release branch to `main` and merge the PR. This way, the latest release and ``main`` are synchronized.

For a full step by step guide, follow the diagram below.

````mermaid
---
config:
  theme: redux
  layout: dagre
---
flowchart TD
 subgraph s3["<b>Semantic version check workflow</b>"]
        n5["Check Semantic Versioning<br>differences between <code>main</code> and <code>dev</code>"]
        n8["Semantic Versioning<br>report (e.g., <code>v2.0.1</code>)"]
  end
 subgraph s6["Legend"]
    direction TB
        n43["Untitled Node"]
        n39["Manual Input"]
        n40["Automatic process"]
        n41["Data"]
        n42["Decision"]
  end
 subgraph s4["URIs Example"]
        n34["...fega-metadata-schema/tree/<b>v2.0.1</b>/..."]
        n35["...fega-metadata-schema/tree/<b>v2.0.1</b>/..."]
  end
 subgraph s5["URIs Example"]
        n36["...fega-metadata-schema/tree/<b>v2.0.1</b>/..."]
        n37["...fega-metadata-schema/tree/<b>main</b>/..."]
  end
 subgraph s2["Release Branch"]
        n1@{ label: "Modify <b>static schema pointers</b> (<code>$id</code>) and <b>data pointers</b> (<code>'schema': '...'</code>) to RB branch" }
        n21["Update <code>release_manifest.json</code>"]
  end
 subgraph s1["<b>Release workflow</b>"]
        n2["Create Release Branch (<b>RB</b>)<br>(e.g., <code>v2.0.1</code>)"]
        n9["Check version name matches changes in dev"]
        n10["Version name<br>matches changes"]
        s2
        n11["Check validation retrieving remote RB repository"]
        n19["Remote validation<br>works with RB"]
        n20["Junction"]
        n33["Stop"]
  end
    n31["<i><b>Start</b></i>"] L_n31_n16_0@--> n16["Trigger validation<br>check for dev branch"]
    n16 L_n16_n14_0@--> n14@{ label: "<font face=\"ui-monospace,\">dev branch<br>is valid</font>" }
    n14 L_n13_n14_0@-- yes --> n13["Trigger Semantic <br>Version check"]
    n13 --> n5 & n22["Update CHANGELOG"]
    n8 -. use as<br>tag name .-> x
    x L_n4_x_0@--> n4
    n4["Trigger release workflow"]
    n8 -. use as<br>tag name .-> n22
    n2 --> n1 & n21
    n5 --> n8
    x@{ shape: f-circ, label: "Junction" }
    n4 L_n4_n9_0@--> n9
    n9 --> n10
    n10 -- yes --> n2
    n2 -. creates .-> s2
    n1 --> n20
    n14 -- no --> n17["Amend errors"]
    n17 --> n16
    n11 --> n19
    n20 --> n11
    n21 --> n20
    n22 L_n22_n4_0@--> x
    n19 -- no --> n17
    n19 L_n19_n28_0@-- yes --> n28["Create PR from<br>RB to main"]
    n24["Remote validation<br>works with release (tag)"] -- no --> n17
    n23["Review PR and<br>changes in RB"] L_n23_n26_0@--> n26["Create GH release<br>and tag (e.g., v2.0.1)"]
    n28 L_n28_n23_0@--> n23
    n27@{ label: "Remote validation<br style=\"--tw-scale-x:\">works with main" }
    n27 L_n29_n27_0@-- yes --> n29
    n29["Merge RB to main"]
    n29 L_n24_n29_0@--> n24
    n27 -- no --> n30["Revert main<br>to pre-release"]
    n30 --> n17
    n10 -- no --> n33
    n34 -- no changes --> n35
    n26 -.-> s4
    n36 -- change to 'main' --> n37
    n28 -.-> s5
    n38@{ label: "Modify static <b>schema pointers</b> (<code>$id</code>) and <b>data pointers</b>(<code>'schema': '...'</code>) to '<b>main</b>' branch" }
    n38 L_n27_n38_0@--> n27
    n26 L_n26_n38_0@--> n38
    n24 L_n32_n24_0@-- yes --> n32["<i><b>End</b></i>"]
    n5@{ shape: proc}
    n8@{ shape: in-out}
    n39@{ shape: manual-input}
    n40@{ shape: proc}
    n41@{ shape: in-out}
    n42@{ shape: decision}
    n34@{ shape: lean-r}
    n35@{ shape: lean-r}
    n36@{ shape: lean-r}
    n37@{ shape: lean-r}
    n1@{ shape: proc}
    n21@{ shape: proc}
    n2@{ shape: proc}
    n9@{ shape: proc}
    n10@{ shape: decision}
    n11@{ shape: proc}
    n19@{ shape: decision}
    n20@{ shape: junction}
    n33@{ shape: stop}
    n31@{ shape: terminal}
    n16@{ shape: manual-input}
    n14@{ shape: decision}
    n13@{ shape: manual-input}
    n22@{ shape: manual-input}
    n4@{ shape: manual-input}
    n17@{ shape: manual-input}
    n24@{ shape: decision}
    n23@{ shape: manual-input}
    n26@{ shape: manual-input}
    n27@{ shape: decision}
    n29@{ shape: manual-input}
    n30@{ shape: manual-input}
    n38@{ shape: manual-input}
    n32@{ shape: terminal}
    style n42 fill:#FFF9C4
    style n10 fill:#FFF9C4
    style n19 fill:#FFF9C4
    style n31 fill:#FFD600
    style n14 fill:#FFF9C4
    style n17 fill:#FFCDD2
    style n24 fill:#FFF9C4
    style n27 fill:#FFF9C4
    style s4 fill:#FFFFFF
    style s5 fill:#FFFFFF
    style n32 fill:#00C853
    style s6 fill:#FFFFFF
    L_n31_n16_0@{ animation: slow } 
    L_n16_n14_0@{ animation: slow } 
    L_n13_n22_0@{ animation: slow } 
    L_n4_n9_0@{ animation: slow } 
    L_n22_n4_0@{ animation: slow } 
    L_n19_n28_0@{ animation: slow } 
    L_n23_n26_0@{ animation: slow } 
    L_n28_n23_0@{ animation: slow } 
    L_n26_n38_0@{ animation: slow }
    L_n27_n38_0@{ animation: slow }
    L_n29_n27_0@{ animation: slow }
    L_n13_n14_0@{ animation: slow }
    L_n24_n29_0@{ animation: slow }
    L_n32_n24_0@{ animation: slow }
    L_n4_x_0@{ animation: slow }
````

## Files generated on every release

| File | Description |
|------|-------------|
| [`release_manifest.json`](release_manifest.json) | Lists `{file, meta.version}` for every schema in the tag, to easily visualize what changed in each release. Validated by [`release_manifest.schema.json`](../../schemas/release_manifest.schema.json). |
| `fega-metadata-schema-X.Y.Z.zip` | Source code (whole repository as a snapshot), attached to the GitHub Release. |

## FAQs

* **"Why the need to change 'pointers'?"**  
  Raw GitHub URLs are used as the URIs for schema ``$id``s. These URIs are specific to branches, tags and releases. Thus, they are to be changed when remote validation is to be asserted. See more at [branching and tags](#branching-and-tags).

* **"Why absolute `$id` URLs with the tag?"**  
  They allow clients to fetch a schema directly from the GitHub CDN without cloning the repo.

* **"How is Semantic Versioning handled with JSON Schemas?"**  
  Major, minor and patch changes are difficult to assess within a JSON Schemas project, given its flexibility and modularity. Overall, version changes in this project encompass uniquely changes within this project and not other related repositories. See more details on how semantic changes are checked through the [``schema_diff.py``](../../scripts/py/schema_diff.py) and its related workflow [``check_schema_diff.yml``](../../.github/workflows/check_schema_diff.yml).

* **"Why check that remote validation works with the release tag _after_ updating ``main``?"**  
  The remote validation is asserted only when the release branch no longer exists, as it's taking the namespace of that URI's version (e.g., ``/v2.0.1/``). Only when it's merged with ``main`` and removed, the ``tag`` (from the release) is what actually is fetched through that URI.

* **"Are draft schemas published?"**  
  Not as releases, but they are publicly available at `dev`. They will not resolve through a versioned URL until you run the release action.