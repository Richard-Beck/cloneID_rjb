#include <TMB.hpp>

template<class Type>
Type stable_softplus(Type x) {
  return logspace_add(Type(0), x);
}

template<class Type>
Type objective_function<Type>::operator() () {
  DATA_VECTOR(y);
  DATA_VECTOR(day);
  DATA_IVECTOR(episode);
  DATA_INTEGER(n_episode);
  DATA_INTEGER(curve_model); // 0 exponential, 1 logistic
  DATA_INTEGER(error_model); // 0 Normal, 1 mean-preserving Lognormal

  PARAMETER_VECTOR(log_intercept); // log(N0_e) or log(A_e)
  PARAMETER_VECTOR(r_state);
  PARAMETER_VECTOR(logK_state);
  PARAMETER(r_initial_mean);
  PARAMETER(log_sigma_r);
  PARAMETER(logK_initial_mean);
  PARAMETER(log_sigma_logK);
  PARAMETER(log_sigma_obs);

  Type sigma_r = exp(log_sigma_r);
  Type sigma_logK = exp(log_sigma_logK);
  Type sigma_obs = exp(log_sigma_obs);
  Type nll = 0;

  // A proper random walk: the first state has the same scale as an innovation.
  nll -= dnorm(r_state(0), r_initial_mean, sigma_r, true);
  for (int e = 1; e < n_episode; ++e) {
    nll -= dnorm(r_state(e), r_state(e - 1), sigma_r, true);
  }

  if (curve_model == 1) {
    nll -= dnorm(logK_state(0), logK_initial_mean, sigma_logK, true);
    for (int e = 1; e < n_episode; ++e) {
      nll -= dnorm(
        logK_state(e), logK_state(e - 1), sigma_logK, true
      );
    }
  }

  for (int i = 0; i < y.size(); ++i) {
    int e = episode(i);
    Type log_mean;
    if (curve_model == 0) {
      log_mean = log_intercept(e) + r_state(e) * day(i);
    } else {
      Type log_denom = stable_softplus(
        log_intercept(e) - r_state(e) * day(i)
      );
      log_mean = logK_state(e) - log_denom;
    }
    if (error_model == 0) {
      nll -= dnorm(y(i), exp(log_mean), sigma_obs, true);
    } else {
      // This is the density on the original count scale. The Jacobian makes
      // Normal and Lognormal marginal likelihoods directly comparable.
      Type meanlog = log_mean - Type(0.5) * sigma_obs * sigma_obs;
      nll -= dnorm(log(y(i)), meanlog, sigma_obs, true) - log(y(i));
    }
  }

  return nll;
}
