export const getBackendVersions = () => {
  const element = document.getElementById("backend-versions");

  if (!element) return {};

  return JSON.parse(element.textContent);
};
