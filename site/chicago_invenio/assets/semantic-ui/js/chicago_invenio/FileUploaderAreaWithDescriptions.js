import React, { useState, useEffect, useRef, Component } from "react";
import PropTypes from "prop-types";
import axios from "axios";
import { i18next } from "@translations/invenio_rdm_records/i18next";
import { useFormikContext, getIn } from "formik";
import _get from "lodash/get";
import Dropzone from "react-dropzone";
import {
  Button,
  Radio,
  Grid,
  Icon,
  Popup,
  Progress,
  Segment,
  Table,
  Header,
  Form,
} from "semantic-ui-react";
import { humanReadableBytes, FeedbackLabel } from "react-invenio-forms";

const getCsrfToken = () =>
  document.cookie
    .split(";")
    .find((c) => c.trim().startsWith("csrftoken="))
    ?.split("=")[1];

// ---- FileTableHeader (unchanged from upstream) ----

const FileTableHeader = ({ filesLocked }) => (
  <Table.Header>
    <Table.Row>
      <Table.HeaderCell>
        {i18next.t("Preview")}{" "}
        <Popup
          content={i18next.t(
            "Choose which file to preview on the published record landing page"
          )}
          trigger={<Icon fitted name="help circle" size="small" />}
        />
      </Table.HeaderCell>
      <Table.HeaderCell>{i18next.t("Filename")}</Table.HeaderCell>
      <Table.HeaderCell>{i18next.t("Size")}</Table.HeaderCell>
      {!filesLocked && (
        <Table.HeaderCell textAlign="center">{i18next.t("Progress")}</Table.HeaderCell>
      )}
      {!filesLocked && <Table.HeaderCell />}
    </Table.Row>
  </Table.Header>
);

FileTableHeader.propTypes = { filesLocked: PropTypes.bool };
FileTableHeader.defaultProps = { filesLocked: false };

// ---- FileTableRow with inline description input ----

const FileTableRowWithDescription = ({
  filesLocked,
  file,
  deleteFile,
  defaultPreview,
  setDefaultPreview,
  decimalSizeDisplay,
  fileError,
  description,
  onDescriptionChange,
  onDescriptionBlur,
}) => {
  const [isCancelling, setIsCancelling] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const isDefaultPreview = defaultPreview === file.name;

  const handleDelete = async (file) => {
    setIsDeleting(true);
    try {
      await deleteFile(file);
      if (isDefaultPreview) {
        setDefaultPreview("");
      }
    } catch (error) {
      setIsDeleting(false);
      console.error(error);
    }
  };

  const handleCancelUpload = (file) => {
    setIsCancelling(true);
    file.cancelUploadFn();
  };

  return (
    <Table.Row key={file.name}>
      <Table.Cell data-label={i18next.t("Default preview")} width={2}>
        <Radio
          checked={isDefaultPreview}
          onChange={() => setDefaultPreview(isDefaultPreview ? "" : file.name)}
        />
      </Table.Cell>
      <Table.Cell data-label={i18next.t("Filename")} width={10}>
        <div>
          {fileError && (
            <>
              <FeedbackLabel
                fieldPath={"files.entries." + file.name}
                pointing="below"
              />
              <br />
            </>
          )}
          {file.uploadState.isPending ? (
            <div>{file.name}</div>
          ) : (
            <a
              href={_get(file, "links.content", "")}
              target="_blank"
              rel="noopener noreferrer"
              className="mr-5 text-break"
            >
              {file.name}
            </a>
          )}
          <br />
          {file.checksum && (
            <div className="ui text-muted">
              <span style={{ fontSize: "10px" }}>{file.checksum}</span>{" "}
              <Popup
                content={i18next.t(
                  "This is the file fingerprint (MD5 checksum), which can be used to verify the file integrity."
                )}
                trigger={<Icon fitted name="help circle" size="small" />}
                position="top center"
              />
            </div>
          )}
          {file.uploadState?.isFinished && file.links?.self && (
            <Form.Field style={{ marginTop: "6px" }}>
              <input
                id={`file-desc-${file.name}`}
                style={{ fontSize: "12px"}}
                type="text"
                placeholder={i18next.t("Optional description for this file")}
                value={description ?? ""}
                onChange={(e) => onDescriptionChange(file.name, e.target.value)}
                onBlur={(e) => onDescriptionBlur(file, e.target.value)}
              />
            </Form.Field>
          )}
        </div>
      </Table.Cell>
      <Table.Cell data-label={i18next.t("Size")} width={2}>
        {file.size
          ? humanReadableBytes(file.size, decimalSizeDisplay)
          : i18next.t("N/A")}
      </Table.Cell>
      {!filesLocked && (
        <Table.Cell
          className="file-upload-pending"
          data-label={i18next.t("Progress")}
          width={2}
        >
          {!file.uploadState?.isPending && (
            <Progress
              className="file-upload-progress primary"
              percent={file.progressPercentage}
              error={file.uploadState.isFailed}
              size="medium"
              progress
              autoSuccess
              active
            />
          )}
          {file.uploadState?.isPending && <span>{i18next.t("Pending")}</span>}
        </Table.Cell>
      )}
      {!filesLocked && (
        <Table.Cell textAlign="right" width={2}>
          {(file.uploadState?.isFinished ||
            file.uploadState?.isFailed ||
            file.uploadState?.isPending) &&
            (isDeleting ? (
              <Icon loading name="spinner" />
            ) : (
              <Icon
                link
                className="action primary"
                name="trash alternate outline"
                disabled={isDeleting}
                onClick={() => handleDelete(file)}
                aria-label={i18next.t("Delete file")}
                title={i18next.t("Delete file")}
              />
            ))}
          {file.uploadState?.isUploading && (
            <Button
              compact
              type="button"
              negative
              size="tiny"
              disabled={isCancelling}
              onClick={() => handleCancelUpload(file)}
            >
              {isCancelling ? <Icon loading name="spinner" /> : i18next.t("Cancel")}
            </Button>
          )}
        </Table.Cell>
      )}
    </Table.Row>
  );
};

FileTableRowWithDescription.propTypes = {
  filesLocked: PropTypes.bool,
  file: PropTypes.object,
  deleteFile: PropTypes.func.isRequired,
  defaultPreview: PropTypes.string,
  setDefaultPreview: PropTypes.func.isRequired,
  decimalSizeDisplay: PropTypes.bool,
  fileError: PropTypes.object,
  description: PropTypes.string,
  onDescriptionChange: PropTypes.func.isRequired,
  onDescriptionBlur: PropTypes.func.isRequired,
};

FileTableRowWithDescription.defaultProps = {
  filesLocked: false,
  file: undefined,
  defaultPreview: undefined,
  decimalSizeDisplay: false,
  fileError: undefined,
  description: undefined,
};

// ---- FilesListTable using our custom row ----

const FilesListTableWithDescriptions = ({
  filesLocked,
  filesList,
  deleteFile,
  decimalSizeDisplay,
  descriptions,
  onDescriptionChange,
  onDescriptionBlur,
}) => {
  const { errors, setFieldValue, values: formikDraft } = useFormikContext();
  const defaultPreview = _get(formikDraft, "files.default_preview", "");
  return (
    <Table>
      <FileTableHeader filesLocked={filesLocked} />
      <Table.Body>
        {filesList.map((file) => (
          <FileTableRowWithDescription
            key={file.name}
            filesLocked={filesLocked}
            file={file}
            deleteFile={deleteFile}
            defaultPreview={defaultPreview}
            setDefaultPreview={(filename) =>
              setFieldValue("files.default_preview", filename)
            }
            decimalSizeDisplay={decimalSizeDisplay}
            fileError={getIn(errors, "files.entries." + file.name, undefined)}
            description={descriptions[file.name]}
            onDescriptionChange={onDescriptionChange}
            onDescriptionBlur={onDescriptionBlur}
          />
        ))}
      </Table.Body>
    </Table>
  );
};

FilesListTableWithDescriptions.propTypes = {
  filesLocked: PropTypes.bool,
  filesList: PropTypes.array,
  deleteFile: PropTypes.func,
  decimalSizeDisplay: PropTypes.bool,
  descriptions: PropTypes.object.isRequired,
  onDescriptionChange: PropTypes.func.isRequired,
  onDescriptionBlur: PropTypes.func.isRequired,
};

FilesListTableWithDescriptions.defaultProps = {
  filesLocked: undefined,
  filesList: undefined,
  deleteFile: undefined,
  decimalSizeDisplay: undefined,
};

// ---- FileUploadBox (unchanged from upstream) ----

const FileUploadBox = ({
  filesLocked,
  filesList,
  dragText,
  hasError,
  uploadButtonIcon,
  uploadButtonText,
  openFileDialog,
}) =>
  !filesLocked && (
    <Segment
      basic
      padded="very"
      className={filesList.length ? "file-upload-area" : "file-upload-area no-files"}
    >
      <Grid columns={3} textAlign="center">
        <Grid.Row verticalAlign="middle">
          <Grid.Column mobile={16} tablet={7} computer={7}>
            <Header size="small">{dragText}</Header>
          </Grid.Column>
          <Grid.Column className="mt-10 mb-10" mobile={16} tablet={2} computer={2}>
            - {i18next.t("or")} -
          </Grid.Column>
          <Grid.Column mobile={16} tablet={7} computer={7}>
            <Button
              type="button"
              className={hasError ? "error" : "primary"}
              labelPosition="left"
              icon={uploadButtonIcon}
              content={uploadButtonText}
              onClick={() => openFileDialog()}
              disabled={openFileDialog === null}
            />
          </Grid.Column>
        </Grid.Row>
      </Grid>
    </Segment>
  );

FileUploadBox.propTypes = {
  filesLocked: PropTypes.bool.isRequired,
  filesList: PropTypes.array,
  hasError: PropTypes.bool,
  dragText: PropTypes.string,
  uploadButtonIcon: PropTypes.node,
  uploadButtonText: PropTypes.string,
  openFileDialog: PropTypes.func,
};

FileUploadBox.defaultProps = {
  filesList: undefined,
  dragText: undefined,
  uploadButtonIcon: undefined,
  uploadButtonText: undefined,
  openFileDialog: null,
  hasError: false,
};

// ---- Main exported component ----

export const FileUploaderAreaWithDescriptions = ({
  filesList,
  filesEnabled,
  dropzoneParams,
  filesLocked,
  deleteFile,
  decimalSizeDisplay,
  ...uiProps
}) => {
  const [descriptions, setDescriptions] = useState({});
  const fetchedRef = useRef(new Set());

  // Fetch existing descriptions for any file that has links.self (existing draft files)
  useEffect(() => {
    const toFetch = (filesList || []).filter(
      (f) => f.links?.self && !fetchedRef.current.has(f.name)
    );
    toFetch.forEach(async (file) => {
      fetchedRef.current.add(file.name);
      try {
        const { data } = await axios.get(file.links.self);
        const description = data?.metadata?.description;
        if (description) {
          setDescriptions((prev) => ({ ...prev, [file.name]: description }));
        }
      } catch (_) {
        // silently ignore — file may not have metadata yet
      }
    });
  }, [filesList]);

  const handleDescriptionChange = (fileName, value) => {
    setDescriptions((prev) => ({ ...prev, [fileName]: value }));
  };

  const handleDescriptionBlur = async (file, value) => {
    if (!file.links?.self) return;
    try {
      await axios.put(
        file.links.self,
        { metadata: { description: value } },
        {
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
          },
        }
      );
    } catch (e) {
      console.error("Failed to save file description:", e);
    }
  };

  if (!filesEnabled) {
    return (
      <Grid.Column width={16}>
        <Segment basic padded="very" className="file-upload-area no-files">
          <Grid textAlign="center">
            <Grid.Row verticalAlign="middle">
              <Grid.Column>
                <Header size="medium">
                  {i18next.t("This is a Metadata-only record.")}
                </Header>
              </Grid.Column>
            </Grid.Row>
          </Grid>
        </Segment>
      </Grid.Column>
    );
  }

  return (
    <Grid.Row className="pt-0 pb-0">
      <Dropzone {...dropzoneParams}>
        {({ getRootProps, getInputProps, open: openFileDialog }) => (
          <Grid.Column width={16}>
            <span {...getRootProps()}>
              <input {...getInputProps()} />
              {filesList.length !== 0 && (
                <Grid.Column verticalAlign="middle">
                  <FilesListTableWithDescriptions
                    filesLocked={filesLocked}
                    filesList={filesList}
                    deleteFile={deleteFile}
                    decimalSizeDisplay={decimalSizeDisplay}
                    descriptions={descriptions}
                    onDescriptionChange={handleDescriptionChange}
                    onDescriptionBlur={handleDescriptionBlur}
                  />
                </Grid.Column>
              )}
              <FileUploadBox
                {...uiProps}
                filesLocked={filesLocked}
                filesList={filesList}
                openFileDialog={openFileDialog}
              />
            </span>
          </Grid.Column>
        )}
      </Dropzone>
    </Grid.Row>
  );
};

FileUploaderAreaWithDescriptions.propTypes = {
  filesList: PropTypes.array,
  filesEnabled: PropTypes.bool,
  dropzoneParams: PropTypes.object,
  filesLocked: PropTypes.bool,
  deleteFile: PropTypes.func,
  decimalSizeDisplay: PropTypes.bool,
};

FileUploaderAreaWithDescriptions.defaultProps = {
  filesList: [],
  filesEnabled: false,
  dropzoneParams: undefined,
  filesLocked: false,
  deleteFile: undefined,
  decimalSizeDisplay: false,
};
