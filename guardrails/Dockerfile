FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 mvn -B -q dependency:go-offline
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 mvn -B -q verify

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /build/target/guardrails-1.0.0.jar app.jar
COPY --from=build /build/target/surefire-reports /app/test-reports
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
