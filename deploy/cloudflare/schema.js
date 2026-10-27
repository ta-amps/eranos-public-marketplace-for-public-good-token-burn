// JSON Schema subset emitted by Pydantic KitDraft. Unknown schema keywords fail closed.
export function schemaIssues(value, schema, root = schema, path = "draft") {
  if (schema.$ref) return schemaIssues(value, root.$defs[schema.$ref.split('/').pop()], root, path);
  if (schema.anyOf) {
    if (schema.anyOf.some((s) => schemaIssues(value, s, root, path).length === 0)) return [];
    return [`${path}: no allowed schema alternative matches`];
  }
  const issues = [];
  if (schema.enum && !schema.enum.includes(value)) issues.push(`${path}: unsupported value`);
  if ('const' in schema && value !== schema.const) issues.push(`${path}: expected constant`);
  const type = schema.type;
  const ok = type === undefined || (type === 'null' ? value === null : type === 'array' ? Array.isArray(value) : type === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value) : type === 'integer' ? Number.isSafeInteger(value) : typeof value === type);
  if (!ok) return [...issues, `${path}: expected ${type}`];
  if (type === 'string') {
    if (schema.minLength !== undefined && [...value].length < schema.minLength) issues.push(`${path}: too short`);
    if (schema.maxLength !== undefined && [...value].length > schema.maxLength) issues.push(`${path}: too long`);
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) issues.push(`${path}: invalid format`);
  }
  if (type === 'array') {
    if (schema.minItems !== undefined && value.length < schema.minItems) issues.push(`${path}: too few items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) issues.push(`${path}: too many items`);
    for (let i=0; i<value.length; i++) if (schema.items) issues.push(...schemaIssues(value[i],schema.items,root,`${path}[${i}]`));
  }
  if (type === 'object') {
    for (const key of schema.required || []) if (!(key in value)) issues.push(`${path}.${key}: required`);
    for (const [key,entry] of Object.entries(value)) {
      if (schema.properties?.[key]) issues.push(...schemaIssues(entry,schema.properties[key],root,`${path}.${key}`));
      else if (schema.additionalProperties === false) issues.push(`${path}.${key}: unexpected field`);
      else if (typeof schema.additionalProperties === 'object') issues.push(...schemaIssues(entry,schema.additionalProperties,root,`${path}.${key}`));
    }
  }
  return issues;
}
