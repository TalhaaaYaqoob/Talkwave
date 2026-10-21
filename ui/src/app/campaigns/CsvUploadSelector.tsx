'use client';

import { AlertCircle, CheckCircle2, FileSpreadsheet, FileWarning } from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { getBackendUrl } from '@/lib/apiClient';
import logger from '@/lib/logger';

interface CsvUploadSelectorProps {
  accessToken: string;
  onFileUploaded: (fileKey: string, fileName: string) => void;
  selectedFileName?: string;
}

interface PresignedUploadUrlResponse {
  upload_url: string;
  file_key: string;
  expires_in: number;
}

interface ValidationResult {
  valid: boolean;
  headers: string[];
  missingColumns: string[];
  rowCount: number;
  emptyPhoneRows: number;
}

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
const REQUIRED_COLUMNS = ['phone_number', 'first_name', 'last_name'];
const ACCEPTED_EXTENSIONS = ['.csv', '.xlsx', '.xls'];
const ACCEPTED_MIME_TYPES = [
  'text/csv',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/vnd.ms-excel',
];

function getFileExtension(name: string): string {
  return name.slice(name.lastIndexOf('.')).toLowerCase();
}

function isExcelFile(name: string): boolean {
  const ext = getFileExtension(name);
  return ext === '.xlsx' || ext === '.xls';
}

function parseCsvHeaders(text: string): string[] {
  const firstLine = text.split(/\r?\n/)[0] || '';
  return firstLine.split(',').map((h) => h.trim().replace(/^["']|["']$/g, ''));
}

function validateCsvContent(text: string): ValidationResult {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length === 0) {
    return { valid: false, headers: [], missingColumns: REQUIRED_COLUMNS, rowCount: 0, emptyPhoneRows: 0 };
  }

  const headers = parseCsvHeaders(text);
  const normalizedHeaders = headers.map((h) => h.toLowerCase().trim());

  const missingColumns = REQUIRED_COLUMNS.filter(
    (col) => !normalizedHeaders.includes(col.toLowerCase())
  );

  const dataRows = lines.length - 1;
  const phoneIndex = normalizedHeaders.indexOf('phone_number');
  let emptyPhoneRows = 0;

  if (phoneIndex >= 0 && dataRows > 0) {
    for (let i = 1; i < lines.length; i++) {
      const cols = lines[i].split(',');
      const phone = (cols[phoneIndex] || '').trim().replace(/^["']|["']$/g, '');
      if (!phone) emptyPhoneRows++;
    }
  }

  return {
    valid: missingColumns.length === 0,
    headers,
    missingColumns,
    rowCount: dataRows,
    emptyPhoneRows,
  };
}

async function excelToValidatedCsv(file: File): Promise<{ csvText: string; csvBlob: Blob; validation: ValidationResult }> {
  const { read, utils } = await import('xlsx');
  const buffer = await file.arrayBuffer();
  const workbook = read(buffer, { type: 'array' });

  const firstSheetName = workbook.SheetNames[0];
  if (!firstSheetName) {
    throw new Error('Excel file has no sheets');
  }

  const sheet = workbook.Sheets[firstSheetName];
  const csvText = utils.sheet_to_csv(sheet);
  const validation = validateCsvContent(csvText);
  const csvBlob = new Blob([csvText], { type: 'text/csv' });

  return { csvText, csvBlob, validation };
}

export default function CsvUploadSelector({ accessToken, onFileUploaded, selectedFileName }: CsvUploadSelectorProps) {
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setValidation(null);

    const ext = getFileExtension(file.name);
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      toast.error('Please select a CSV or Excel (.xlsx, .xls) file');
      return;
    }

    if (file.size > MAX_FILE_SIZE) {
      toast.error('File size must be less than 10MB');
      return;
    }

    let csvBlob: Blob;
    let csvFileName: string;
    let result: ValidationResult;

    try {
      if (isExcelFile(file.name)) {
        const parsed = await excelToValidatedCsv(file);
        result = parsed.validation;
        csvBlob = parsed.csvBlob;
        csvFileName = file.name.replace(/\.(xlsx|xls)$/i, '.csv');
        setValidation(result);
      } else {
        const csvText = await file.text();
        result = validateCsvContent(csvText);
        csvBlob = file;
        csvFileName = file.name;
        setValidation(result);
      }

      if (!result.valid) {
        toast.error(
          `File is missing required column(s): ${result.missingColumns.join(', ')}. Please fix your file and re-upload.`
        );
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }

      if (result.rowCount === 0) {
        toast.error('File has no data rows. Please add at least one contact.');
        if (fileInputRef.current) fileInputRef.current.value = '';
        return;
      }
    } catch {
      toast.error('Failed to read file. Please check the file format.');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    setUploading(true);
    setUploadProgress(0);

    try {
      logger.info('Requesting presigned upload URL for:', csvFileName);
      const presignedResponse = await fetch(`${getBackendUrl()}/api/v1/s3/presigned-upload-url`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          file_name: csvFileName,
          file_size: csvBlob.size,
          content_type: 'text/csv',
        }),
      });

      if (!presignedResponse.ok) {
        const error = await presignedResponse.json();
        throw new Error(error.detail || 'Failed to get upload URL');
      }

      const presignedData: PresignedUploadUrlResponse = await presignedResponse.json();
      logger.info('Received presigned URL, uploading file...');

      const uploadResponse = await fetch(presignedData.upload_url, {
        method: 'PUT',
        body: csvBlob,
        headers: {
          'Content-Type': 'text/csv',
        },
      });

      if (!uploadResponse.ok) {
        throw new Error('Failed to upload file to storage');
      }

      setUploadProgress(100);
      logger.info('File uploaded successfully, file_key:', presignedData.file_key);

      onFileUploaded(presignedData.file_key, file.name);
      toast.success(`File uploaded: ${file.name}`);
    } catch (error) {
      logger.error('Error uploading file:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to upload file');
    } finally {
      setUploading(false);
      setUploadProgress(0);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="space-y-3">
      <Label>Upload File</Label>
      <div className="flex items-center gap-4">
        <input
          ref={fileInputRef}
          type="file"
          accept={[...ACCEPTED_EXTENSIONS, ...ACCEPTED_MIME_TYPES].join(',')}
          onChange={handleFileSelect}
          className="hidden"
        />
        <Button
          type="button"
          variant="outline"
          onClick={handleButtonClick}
          disabled={uploading}
        >
          <FileSpreadsheet className="h-4 w-4 mr-2" />
          {uploading ? `Uploading... ${uploadProgress}%` : 'Upload CSV / Excel File'}
        </Button>
        {selectedFileName && !uploading && (
          <div className="flex-1 text-sm">
            <span className="text-muted-foreground">Selected: </span>
            <span className="text-primary">{selectedFileName}</span>
          </div>
        )}
      </div>

      {/* Validation feedback */}
      {validation && !validation.valid && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 space-y-2">
          <div className="flex items-center gap-2 text-destructive text-sm font-medium">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            Missing required columns
          </div>
          <div className="flex flex-wrap gap-1.5">
            {REQUIRED_COLUMNS.map((col) => (
              <Badge
                key={col}
                variant={validation.missingColumns.includes(col) ? 'destructive' : 'outline'}
                className="text-xs"
              >
                {validation.missingColumns.includes(col) ? (
                  <AlertCircle className="h-3 w-3 mr-1" />
                ) : (
                  <CheckCircle2 className="h-3 w-3 mr-1" />
                )}
                {col}
              </Badge>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Your file has columns: {validation.headers.join(', ') || '(none)'}
          </p>
        </div>
      )}

      {validation && validation.valid && selectedFileName && (
        <div className="rounded-md border border-green-500/30 bg-green-500/10 p-3 space-y-1">
          <div className="flex items-center gap-2 text-green-400 text-sm font-medium">
            <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
            File validated successfully
          </div>
          <p className="text-xs text-muted-foreground">
            {validation.rowCount} contact(s) found
            {validation.emptyPhoneRows > 0 && (
              <span className="text-amber-400">
                {' '} ({validation.emptyPhoneRows} row(s) missing phone_number will be skipped)
              </span>
            )}
          </p>
        </div>
      )}

      <div className="rounded-md border border-border/50 bg-muted/30 p-3">
        <div className="flex items-start gap-2">
          <FileWarning className="h-4 w-4 mt-0.5 flex-shrink-0 text-muted-foreground" />
          <div className="text-xs text-muted-foreground space-y-1">
            <p className="font-medium">Required file format:</p>
            <p>Your CSV or Excel file <span className="text-white font-medium">must</span> include these columns:</p>
            <div className="flex gap-1.5 mt-1">
              {REQUIRED_COLUMNS.map((col) => (
                <Badge key={col} variant="secondary" className="text-xs font-mono">{col}</Badge>
              ))}
            </div>
            <p className="mt-1">
              Supported formats: <span className="font-medium">.csv</span>, <span className="font-medium">.xlsx</span>, <span className="font-medium">.xls</span>.
              {' '}Excel files are automatically converted. Additional columns will be passed as context variables. Max 10MB.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
