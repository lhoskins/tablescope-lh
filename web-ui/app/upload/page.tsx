"use client";

import { FileDropzone } from "@/components/upload/FileDropzone";

export default function UploadPage() {
  return (
    <section>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Upload Files</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload data files (CSV, Excel) to your personal Teiid folder. Files
          are stored in your private workspace and can be queried through your
          UserVDB.
        </p>
      </header>
      <FileDropzone
        onUploaded={(result) => {
          console.log("Uploaded:", result);
        }}
      />
    </section>
  );
}
