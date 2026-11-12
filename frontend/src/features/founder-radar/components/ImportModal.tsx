import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button, Callout, Field, Modal } from "@/components/ui";
import { useImport } from "../api";
import { fileNote, importToast } from "../model/view";
import styles from "../FounderRadar.module.css";

/** "Authorized import (CSV / TSV)": the file is read in the browser (FileReader) into the text box, reviewed, then
 *  posted as `{csv, label, include_email}`. E-mail addresses are kept only when the operator asks. */
export function ImportModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const [label, setLabel] = useState("");
  const [csv, setCsv] = useState("");
  const [email, setEmail] = useState(false);
  const [note, setNote] = useState("choose Connections.csv / .tsv — or paste below");
  const imp = useImport();

  const pick = (file: File | undefined) => {
    if (!file) return;
    const rd = new FileReader();
    rd.onload = () => {
      setCsv(String(rd.result ?? ""));
      setNote(fileNote(file.name, file.size));
    };
    rd.readAsText(file);
  };

  const run = async () => {
    try {
      const r = await imp.mutateAsync({ csv, label, include_email: email });
      toast.show(importToast(r), "ok");
      setCsv("");
      onClose();
    } catch {
      /* toasted */
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Authorized import (CSV / TSV)"
      width={720}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={run} busy={imp.isPending} disabled={!csv.trim()}>
            Import
          </Button>
        </>
      }
    >
      <div className={styles.askForm} data-testid="fr-import">
        <Callout tone="blue">
          Two accepted formats: the <b>official LinkedIn Connections export</b> (First Name, Last Name, URL, Email Address, Company, Position, Connected On —
          preamble lines are handled) or the custom format (name, linkedin, company, role, location, country). Rows become identity-unresolved records with
          import provenance; nothing is verified, scored or promoted automatically. Nothing is scanned from LinkedIn — no cookies, no automation.
        </Callout>
        <Field label="Label">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="label, e.g. 'LinkedIn Connections export 2026-09'" />
        </Field>
        <Field label="File" hint={note}>
          <input type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" onChange={(e) => pick(e.target.files?.[0])} data-testid="fr-import-file" />
        </Field>
        <Field label="CSV / TSV">
          <textarea rows={8} value={csv} onChange={(e) => setCsv(e.target.value)} placeholder="paste CSV / TSV here" />
        </Field>
        <label className={styles.check}>
          <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} /> also keep e-mail addresses (off by default)
        </label>
      </div>
    </Modal>
  );
}
