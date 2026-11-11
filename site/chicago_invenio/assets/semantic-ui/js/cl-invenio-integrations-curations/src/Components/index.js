// Everything in this file represents a component that we have used
// internally in one or more implementations which is NOT exported
// from the parent module. That meeans that location is an implementation
// detail and is NOT considered under semantic breaking changes,
// and so we re-export here for safety until it is exported as normal.
// At that point we can set the public export as the path here with a
// deprecation notice maybe? "This can now be imported from a public path,
// do that directly instead of using this proxied export". Not sure exactly
// what the best route froward is there.

export { CustomDepositStatusBox } from
  "@js/invenio_curations/deposit/CustomDepositStatusBox";
export { RequestOrPublishButton } from
  "@js/invenio_curations/deposit/RequestOrPublishButton";