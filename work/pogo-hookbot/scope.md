# Case Scope

## meta
- case_id: pogo-hookbot
- created: 2026-10-28T21:02:14-05:00
- operator: local
- project_root: /home/walbarellos/cracklab/fonelora-linux
- primary_skill: apk-reverse/SKILL.md
- primary_id: R1
- lead_role: lead
- specialist_roles: []
- hint: Android APK Unity IL2CPP in-app ZeroMQ plugin hook bot automation
- preset: none

## auth
- status: granted
- basis: own_system
- evidence_of_auth: user-owned lab; pokemon_custom.apk is a local sample under user control
- MUST NOT proceed if status != granted

## in_scope
- assets:
  - /home/walbarellos/cracklab/fonelora-linux/pokemon_custom.apk
- surfaces: []
- activities: []

## out_of_scope
- assets: []
- activities: [dos, phishing_real_users, unrestricted_exfil]

## network_profile
- mode: offline
- notes: |
    offline | lab_only | authorized_target_only | unrestricted_lab
    Change mode only after auth.status = granted.
    Presets: offline-sample | ctf-public | own-system

## deliverables
- report: true
- field_journal: true
- diagrams: true
- timeline: true

## constraints
- timebox: {}
- stealth: low
- data_handling: anonymize

## signoff
- ready_for_act: true
- checklist:
  - [x] auth.status = granted
  - [x] in_scope.assets non-empty OR offline sample path set
  - [x] network_profile.mode chosen
  - [ ] out_of_scope reviewed
  - [ ] roles assigned (see skills/ops/role-map.md)

## ops_refs
- skills/ops/scope-contract.md
- skills/ops/evidence-finding-path.md
- skills/ops/role-map.md
- skills/ops/timeline-workitem.md
- skills/ops/IDENTITY.md
