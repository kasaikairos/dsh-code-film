/* Helpers use linear light and a signed field that is positive inside a shape. */
float filmCoverage(float field) {
    float span = max(fwidth(field), 1e-6);
    return smoothstep(-0.5*span, 0.5*span, field);
}

vec3 filmTransmit(vec3 surface, vec3 mediumLight, vec3 extinction, float distance) {
    vec3 transmission = exp(-max(extinction, vec3(0.0))*max(distance, 0.0));
    return surface*transmission + mediumLight*(1.0-transmission);
}

vec3 filmFresnel(vec3 normalReflectance, float cosTheta) {
    float grazing = 1.0-clamp(cosTheta,0.0,1.0);
    return normalReflectance+(1.0-normalReflectance)*pow(grazing,5.0);
}

vec3 filmToSrgb(vec3 linearRGB) {
    vec3 color = clamp(linearRGB,0.0,1.0);
    return mix(12.92*color,1.055*pow(color,vec3(1.0/2.4))-0.055,
               greaterThan(color,vec3(0.0031308)));
}

/* Fade unresolved periodic relief into its zero-mean surface. Call from uniform flow. */
float filmResolvedSine(float phase) {
    float footprint = fwidth(phase);
    return sin(phase)*(1.0-smoothstep(1.2,3.14159265,footprint));
}

/* Project each wave's pixel footprint onto its own direction before filtering.
   Derivatives of world position must be evaluated in uniform control flow. */
float filmWaveBand(vec2 axis, float wavelength, vec2 worldDx, vec2 worldDy) {
    float footprint=max(abs(dot(axis,worldDx)),abs(dot(axis,worldDy)));
    return 1.0-smoothstep(0.23,0.65,footprint/max(wavelength,1e-6));
}
