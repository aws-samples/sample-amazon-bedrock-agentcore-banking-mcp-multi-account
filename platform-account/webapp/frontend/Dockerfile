FROM node:20-alpine AS build
WORKDIR /app
ARG REACT_APP_OKTA_ISSUER
ARG REACT_APP_OKTA_CLIENT_ID
ENV REACT_APP_OKTA_ISSUER=$REACT_APP_OKTA_ISSUER
ENV REACT_APP_OKTA_CLIENT_ID=$REACT_APP_OKTA_CLIENT_ID
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
